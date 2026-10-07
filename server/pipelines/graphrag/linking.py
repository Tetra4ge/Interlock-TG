import json
import re
import time
from functools import cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field
from rapidfuzz import fuzz

from server.common.logging import get_logger
from server.common.timing import timer
from server.graph.queries import entity_search
from server.llm.gateway import SpendCapExceeded, call_llm
from server.llm.models import LLMMessage, LLMRequest
from server.pipelines.common.answer import DEFAULT_MODEL
from server.pipelines.common.scope import COMPANIES_PATH, FISCAL_YEAR, detect_fiscal_year
from server.pipelines.common.tracer import Tracer
from server.pipelines.config import GRAPHRAG, GraphRAGConfig
from server.resolve.normalize import norm_company, norm_person

logger = get_logger(__name__)

PROMPT_PATH = Path(__file__).resolve().parent / "prompts/link_v1.md"
RELATION_TYPES = (
    "DIRECTOR_OF",
    "HOLDS_STAKE",
    "SUBSIDIARY_OF",
    "AUDITED_BY",
    "PARTY_TO",
    "NAMED_IN",
    "IN_SECTOR",
)
MENTION_KINDS = ("company", "person", "audit_firm", "sector", "unknown")
MAX_AMBIGUOUS_KEPT = 2
# Candidates scored before cutting to the best match. entity_search ranks by
# token_sort_ratio but linking decides on token_set_ratio, so the pool must be
# wide enough that the real match is not truncated away first.
CANDIDATE_POOL = 25

_INTERROGATIVES = {
    "who", "what", "which", "when", "where", "why", "how", "is", "are", "was", "were", "did",
    "does", "do", "list", "name", "show", "tell", "give", "find", "the", "a", "an", "in", "of",
    "for", "and", "between", "compare",
}  # fmt: skip
_HONORIFIC_PREFIX = re.compile(r"^(?:mr|mrs|ms|shri|smt|sri)\.?\s+", re.IGNORECASE)
_CAP_PHRASE = re.compile(
    r"[A-Z][\w&.'-]*(?:\s+(?:&|of|and|for|[A-Z][\w&.'-]*))*(?<![\s&])",
)


class Mention(BaseModel):
    text: str
    kind: str = "unknown"


class LinkPlan(BaseModel):
    mentions: list[Mention] = Field(default_factory=list)
    relation_types: list[str] = Field(default_factory=list)
    fiscal_years: list[str] = Field(default_factory=list)
    is_global: bool = False
    source: Literal["llm", "fallback"] = "llm"


class LinkedEntity(BaseModel):
    mention: str
    entity_id: str = ""
    name: str = ""
    kind: str = ""
    score: float = 0.0
    status: Literal["linked", "ambiguous", "unlinked"] = "unlinked"


def _normalize_fiscal_years(values: object) -> list[str]:
    out: list[str] = []
    for v in values if isinstance(values, list) else []:
        m = FISCAL_YEAR.search(str(v))
        fy = f"FY{m.group(1)}-{m.group(2)}" if m else None
        if fy and fy not in out:
            out.append(fy)
    return out


def parse_plan(raw: str, question: str) -> LinkPlan:
    """Validate the helper model's JSON. Unknown relation types and malformed
    years are dropped rather than trusted; a year written in the question is
    always honoured even if the model forgot it."""
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("plan is not a JSON object")

    mentions = []
    for m in data.get("mentions") or []:
        if isinstance(m, dict) and str(m.get("text", "")).strip():
            kind = str(m.get("kind", "unknown")).lower()
            mentions.append(
                Mention(
                    text=str(m["text"]).strip(), kind=kind if kind in MENTION_KINDS else "unknown"
                )
            )

    relations = [
        r for r in (str(x).upper() for x in data.get("relation_types") or []) if r in RELATION_TYPES
    ]
    years = _normalize_fiscal_years(data.get("fiscal_years"))
    stated = detect_fiscal_year(question)
    if stated and stated not in years:
        years.append(stated)

    return LinkPlan(
        mentions=mentions,
        relation_types=list(dict.fromkeys(relations)),
        fiscal_years=years,
        is_global=bool(data.get("is_global", False)),
        source="llm",
    )


def capitalized_phrases(question: str) -> list[str]:
    phrases: list[str] = []
    for raw in _CAP_PHRASE.findall(question):
        words = raw.split()
        while words and words[0].lower().strip(".,?") in _INTERROGATIVES:
            words.pop(0)
        while words and words[-1].lower() in {"and", "of", "for", "&"}:
            words.pop()
        phrase = _HONORIFIC_PREFIX.sub("", " ".join(words)).strip(" .,?;:")
        phrase = re.sub(r"['\u2019]s?$", "", phrase).strip()
        if not phrase or FISCAL_YEAR.fullmatch(phrase) or re.fullmatch(r"FY\d.*", phrase):
            continue
        if phrase.lower() in _INTERROGATIVES or phrase in phrases:
            continue
        phrases.append(phrase)
    return phrases


def fallback_plan(question: str) -> LinkPlan:
    """Used when the helper call fails: capitalised phrases become mentions, the
    relation set stays empty (relations.py then widens to all types), and only a
    year written in the question is used."""
    year = detect_fiscal_year(question)
    return LinkPlan(
        mentions=[Mention(text=p) for p in capitalized_phrases(question)],
        fiscal_years=[year] if year else [],
        source="fallback",
    )


def plan_question(question: str, tracer: Tracer, model: str = DEFAULT_MODEL) -> LinkPlan:
    prompt = PROMPT_PATH.read_text().replace("{question}", question)
    req = LLMRequest(
        provider="groq",
        model=model,
        messages=[LLMMessage(role="user", content=prompt)],
        json_mode=True,
        temperature=0.0,
        max_tokens=400,
    )
    try:
        with timer() as t:
            resp = call_llm(req)
    except SpendCapExceeded:
        raise
    except Exception as e:
        tracer.add("llm", "link_plan", question, "", error=f"fallback: {e!r}")
        return fallback_plan(question)

    error = resp.error
    plan: LinkPlan | None = None
    if not error:
        try:
            plan = parse_plan(resp.content, question)
        except (ValueError, TypeError) as e:  # json.JSONDecodeError is a ValueError
            error = f"unparseable plan: {e}"

    tracer.add(
        "llm",
        "link_plan",
        question,
        resp.content[:1000],
        resp.tokens_in,
        resp.tokens_out,
        resp.cost_usd,
        t["ms"],
        error=f"fallback: {error}" if error else None,
    )
    return plan if plan is not None else fallback_plan(question)


@cache
def _sector_members() -> dict[str, list[str]]:
    data = yaml.safe_load(COMPANIES_PATH.read_text()) or {}
    members: dict[str, list[str]] = {}
    for c in data.get("companies", []):
        if c.get("sector"):
            members.setdefault(c["sector"], []).append(f"C:{c['company_id']}")
    return members


def companies_in_sector(sector: str) -> list[str]:
    return list(_sector_members().get(sector, []))


def _normalize(text: str, kind: str) -> str:
    return norm_person(text) if kind == "person" else norm_company(text)


def _match_score(mention: str, cand: dict) -> int:
    kind = cand["kind"]
    m = _normalize(mention, kind)
    return int(
        max((fuzz.token_set_ratio(m, _normalize(n, kind)) for n in cand["names"]), default=0)
    )


def link_sector(mention: Mention, cfg: GraphRAGConfig) -> LinkedEntity | None:
    best_name, best = "", 0.0
    for name in _sector_members():
        score = fuzz.token_set_ratio(norm_company(mention.text), norm_company(name))
        if score > best:
            best_name, best = name, score
    if best < cfg.link_min_score:
        return None
    return LinkedEntity(
        mention=mention.text,
        entity_id=best_name,
        name=best_name,
        kind="sector",
        score=best,
        status="linked",
    )


def link_mention(mention: Mention, cfg: GraphRAGConfig = GRAPHRAG) -> list[LinkedEntity]:
    """One mention -> 0..2 entities. A clear winner is linked; near-ties keep
    up to two as `ambiguous` so expansion and the answer model can disambiguate;
    nothing above the threshold is `unlinked`."""
    if mention.kind == "sector":
        hit = link_sector(mention, cfg)
        return [hit] if hit else [LinkedEntity(mention=mention.text)]

    kind = mention.kind if mention.kind in ("company", "person", "audit_firm") else None
    cands = entity_search(mention.text, kind, limit=CANDIDATE_POOL)
    if not cands and kind:
        # The helper model may have mislabelled the kind ("Deloitte" as a company).
        cands = entity_search(mention.text, None, limit=CANDIDATE_POOL)

    scored = []
    for c in cands:
        score = _match_score(mention.text, c)
        if score >= cfg.link_min_score:
            scored.append((score, c["score"], c))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)

    if not scored:
        return [LinkedEntity(mention=mention.text)]

    top = scored[0]
    clear = len(scored) == 1 or top[0] - scored[1][0] >= cfg.link_score_gap
    keep = scored[:1] if clear else scored[:MAX_AMBIGUOUS_KEPT]
    status: Literal["linked", "ambiguous"] = "linked" if clear else "ambiguous"
    return [
        LinkedEntity(
            mention=mention.text,
            entity_id=c["entity_id"],
            name=c["canonical_name"],
            kind=c["kind"],
            score=float(s),
            status=status,
        )
        for s, _, c in keep
    ]


def link_entities(
    mentions: list[Mention], tracer: Tracer, cfg: GraphRAGConfig = GRAPHRAG
) -> list[LinkedEntity]:
    t0 = time.perf_counter()
    linked: list[LinkedEntity] = []
    for m in mentions:
        linked.extend(link_mention(m, cfg))

    seen: set[str] = set()
    unique = []
    for le in linked:
        if le.entity_id and le.entity_id in seen:
            continue
        seen.add(le.entity_id)
        unique.append(le)

    summary = "; ".join(
        f"{le.mention!r} -> {le.entity_id or 'none'} ({le.status}, {le.score:.0f})" for le in unique
    )
    tracer.add(
        "retrieve",
        "link_entities",
        ", ".join(m.text for m in mentions) or "(no mentions)",
        summary or "no mentions to link",
        latency_ms=int((time.perf_counter() - t0) * 1000),
    )
    return unique


def usable(linked: list[LinkedEntity]) -> list[LinkedEntity]:
    return [le for le in linked if le.status != "unlinked" and le.entity_id]
