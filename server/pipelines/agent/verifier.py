import json
import math
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from server.common.timing import timer
from server.eval.normalize import parse_number_crore
from server.llm.gateway import SpendCapExceeded, call_llm
from server.llm.models import LLMMessage, LLMRequest
from server.pipelines.common.answer import DEFAULT_MODEL
from server.pipelines.common.render import LabeledEvidence, render_blocks
from server.pipelines.common.tracer import Tracer
from server.pipelines.models import AnswerType, ModelAnswer

PROMPT_PATH = Path(__file__).resolve().parent / "prompts/verifier_v1.md"
# Same model as every pipeline's answerer, so the comparison stays like-for-like.
VERIFIER_MODEL = DEFAULT_MODEL
VERIFIER_MAX_TOKENS = 1000
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
NUMBER_REL_TOL = 0.01


class Claim(BaseModel):
    claim: str
    verdict: Literal["SUPPORTED", "UNSUPPORTED"]
    evidence_labels: list[str] = Field(default_factory=list)


class VerifierOutput(BaseModel):
    claims: list[Claim]


class VerifyResult(BaseModel):
    claims: list[Claim] = Field(default_factory=list)
    failed: bool = False  # the verifier itself could not run; the draft is kept

    @property
    def unsupported(self) -> list[Claim]:
        return [c for c in self.claims if c.verdict == "UNSUPPORTED"]

    @property
    def supported(self) -> list[Claim]:
        return [c for c in self.claims if c.verdict == "SUPPORTED"]

    @property
    def ok(self) -> bool:
        return not self.failed and not self.unsupported


def _numbers(text: str) -> list[float]:
    out = []
    for raw in NUMBER.findall(text):
        try:
            out.append(float(raw.replace(",", "")))
        except ValueError:
            continue
    return out


def number_supported(answer_short: str, labels: dict[str, LabeledEvidence]) -> bool:
    """A numeric answer must appear in the evidence: a fact that states it or a
    calculate result that produced it, after unit normalisation (the answer may be
    in crore while a fact is shown in crore or rupees)."""
    targets = _numbers(answer_short)
    normalised = parse_number_crore(answer_short)
    if normalised is not None:
        targets.append(normalised)
    if not targets:
        return True  # nothing numeric to check
    seen = [v for le in labels.values() for v in _numbers(le.item.text)]
    return any(
        math.isclose(t, v, rel_tol=NUMBER_REL_TOL, abs_tol=1e-9) for t in targets for v in seen
    )


def _normalise_claims(claims: list[Claim], labels: dict[str, LabeledEvidence]) -> list[Claim]:
    """A SUPPORTED verdict must name at least one evidence label that exists."""
    out = []
    for c in claims:
        valid = [e for e in c.evidence_labels if e in labels]
        if c.verdict == "SUPPORTED" and not valid:
            c = c.model_copy(update={"verdict": "UNSUPPORTED"})
        out.append(c.model_copy(update={"evidence_labels": valid}))
    return out


def verify_answer(
    tracer: Tracer,
    answer: ModelAnswer,
    labels: dict[str, LabeledEvidence],
    model: str = VERIFIER_MODEL,
) -> VerifyResult:
    """Claim-level check of the draft against the evidence it was given, plus a
    code check that a numeric answer really appears in that evidence. Never
    raises (except the spend cap): if the verifier cannot run the draft stands
    and the trace says verify_failed."""
    prompt = (
        PROMPT_PATH.read_text()
        .replace("{evidence_blocks}", render_blocks(labels))
        .replace("{answer_long}", answer.answer_long)
    )
    request = LLMRequest(
        provider="groq",
        model=model,
        messages=[LLMMessage(role="user", content=prompt)],
        json_mode=True,
        temperature=0.0,
        max_tokens=VERIFIER_MAX_TOKENS,
    )
    try:
        with timer() as t:
            resp = call_llm(request)
    except SpendCapExceeded:
        raise
    except Exception as e:
        tracer.add("verify", "verifier", answer.answer_short, "", error=f"verify_failed: {e!r}")
        return VerifyResult(failed=True)

    error = resp.error
    claims: list[Claim] = []
    if not error:
        try:
            claims = VerifierOutput.model_validate(json.loads(resp.content)).claims
        except (ValueError, ValidationError, TypeError) as e:
            error = f"unparseable verifier output: {e}"[:300]

    tracer.add(
        "verify",
        "verifier",
        answer.answer_short,
        resp.content[:1000],
        resp.tokens_in,
        resp.tokens_out,
        resp.cost_usd,
        t["ms"],
        error=f"verify_failed: {error}" if error else None,
    )
    if error:
        return VerifyResult(failed=True)

    claims = _normalise_claims(claims, labels)
    if answer.answer_type == AnswerType.NUMBER and not number_supported(
        answer.answer_short, labels
    ):
        claims.append(
            Claim(
                claim=f"the number {answer.answer_short!r} appears in no evidence",
                verdict="UNSUPPORTED",
            )
        )
    return VerifyResult(claims=claims)
