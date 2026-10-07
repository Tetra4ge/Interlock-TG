from functools import cache

import yaml

from server.pipelines.common.scope import COMPANIES_PATH
from server.pipelines.config import GRAPHRAG, GraphRAGConfig
from server.pipelines.graphrag.models import Triple
from server.resolve.normalize import norm_company, norm_person

W_TOUCHES_LINKED = 3.0
W_RELATION_REQUESTED = 2.0
W_FISCAL_YEAR = 1.5
W_HOP1 = 1.0
W_MENTIONED = 1.0
W_IN_DATASET = 0.5
MIN_NAME_CHARS = 4


@cache
def dataset_company_ids() -> frozenset[str]:
    data = yaml.safe_load(COMPANIES_PATH.read_text()) or {}
    return frozenset(f"C:{c['company_id']}" for c in data.get("companies", []))


def _mentioned(entity_id: str, names: dict[str, tuple[str, str]], norm_question: str) -> bool:
    name, kind = names.get(entity_id, ("", ""))
    if not name:
        return False
    norm = norm_person(name) if kind == "person" else norm_company(name)
    return len(norm) >= MIN_NAME_CHARS and norm in norm_question


def score_triple(
    t: Triple,
    linked_ids: set[str],
    requested: set[str],
    fiscal_years: list[str],
    norm_question: str,
    names: dict[str, tuple[str, str]],
) -> float:
    score = 0.0
    if linked_ids & set(t.endpoints()):
        score += W_TOUCHES_LINKED
    if t.rel in requested:
        score += W_RELATION_REQUESTED
    if fiscal_years and t.fiscal_year in fiscal_years:
        score += W_FISCAL_YEAR
    if t.hop == 1:
        score += W_HOP1
    if any(_mentioned(e, names, norm_question) for e in t.endpoints()):
        score += W_MENTIONED
    if any(e in dataset_company_ids() for e in t.endpoints()):
        score += W_IN_DATASET
    return score


def _units(triples: list[Triple]) -> list[list[Triple]]:
    """A transaction and its counterparty edge travel together."""
    by_txn: dict[str, list[Triple]] = {}
    units: list[list[Triple]] = []
    for t in triples:
        if t.txn_id:
            if t.txn_id not in by_txn:
                by_txn[t.txn_id] = []
                units.append(by_txn[t.txn_id])
            by_txn[t.txn_id].append(t)
        else:
            units.append([t])
    return units


def rank_and_cap(
    triples: list[Triple],
    linked_ids: set[str],
    requested: set[str],
    fiscal_years: list[str],
    question: str,
    names: dict[str, tuple[str, str]],
    cfg: GraphRAGConfig = GRAPHRAG,
) -> list[Triple]:
    """Score, de-duplicate and cap at `max_triples`, reserving at least
    `min_per_relation` slots per requested relation type so one abundant type
    cannot crowd out another. The result is ordered best-first."""
    unique = list({t.edge_id: t for t in triples}.values())
    norm_question = norm_company(question)
    scores = {
        t.edge_id: score_triple(t, linked_ids, requested, fiscal_years, norm_question, names)
        for t in unique
    }
    units = _units(unique)
    unit_score = {id(u): max(scores[t.edge_id] for t in u) for u in units}
    units.sort(key=lambda u: (-unit_score[id(u)], u[0].edge_id))

    chosen: list[list[Triple]] = []
    chosen_ids: set[int] = set()
    used = 0

    def take(unit: list[Triple]) -> None:
        nonlocal used
        chosen.append(unit)
        chosen_ids.add(id(unit))
        used += len(unit)

    for rel in sorted(requested):
        reserved = 0
        for u in units:
            if reserved >= cfg.min_per_relation:
                break
            if (
                u[0].rel == rel
                and not any(u is c for c in chosen)
                and used + len(u) <= cfg.max_triples
            ):
                take(u)
                reserved += 1
    for u in units:
        if used + len(u) <= cfg.max_triples and id(u) not in chosen_ids:
            take(u)

    chosen.sort(key=lambda u: (-unit_score[id(u)], u[0].edge_id))
    return [t for u in chosen for t in u]
