import time
from collections import defaultdict
from typing import Any

from server.graph.queries import GraphQueryError, run_installed_strict
from server.graph.stats import hub_ids
from server.pipelines.common.tracer import Tracer
from server.pipelines.config import GRAPHRAG, GraphRAGConfig
from server.pipelines.graphrag.linking import LinkedEntity, companies_in_sector
from server.pipelines.graphrag.models import (
    FACT_EDGES,
    REVERSE_TO_FORWARD,
    Triple,
    synthetic_edge_id,
)
from server.pipelines.graphrag.relations import RelationChoice

QUERY_NAME = "expand_hop"
NO_EXCLUSIONS = ["-"]  # an empty SET<STRING> would not be encoded into the request
MAX_FRONTIER = 100
EXPANDABLE_TYPES = {"Company", "Person", "AuditFirm"}
RETRY_FANOUT_FACTOR = 2


class ExpansionFailed(RuntimeError):
    """The graph could not be expanded even after a retry with a smaller fan-out."""


def seed_ids(linked: list[LinkedEntity]) -> list[str]:
    """Graph vertex ids to expand from. A sector has no fact edges of its own, so
    it stands for the dataset companies in that sector."""
    ids: list[str] = []
    for le in linked:
        members = companies_in_sector(le.entity_id) if le.kind == "sector" else [le.entity_id]
        for i in members:
            if i and i not in ids:
                ids.append(i)
    return ids


def _edge_blocks(raw: Any) -> tuple[list[dict], dict[str, dict]]:
    """runInstalledQuery returns [{"edges": [...]}, {"txns": [...]}]; keep both."""
    edges: list[dict] = []
    txns: dict[str, dict] = {}
    for block in raw if isinstance(raw, list) else []:
        if not isinstance(block, dict):
            continue
        edges.extend(e for e in block.get("edges") or [] if isinstance(e, dict))
        for v in block.get("txns") or []:
            if isinstance(v, dict) and v.get("v_id"):
                txns[str(v["v_id"])] = v.get("attributes") or {}
    return edges, txns


def parse_triples(raw: Any, hop: int) -> list[Triple]:
    """Normalise raw edge objects into forward-direction triples, de-duplicated by
    edge_id. Edges missing an id (stake / order / sector edges carry no provenance
    attributes) get a deterministic one."""
    edges, txns = _edge_blocks(raw)
    out: dict[str, Triple] = {}
    for e in edges:
        rel = str(e.get("e_type") or e.get("type") or "")
        src, src_t = str(e.get("from_id", "")), str(e.get("from_type", ""))
        dst, dst_t = str(e.get("to_id", "")), str(e.get("to_type", ""))
        if rel in REVERSE_TO_FORWARD:
            rel = REVERSE_TO_FORWARD[rel]
            src, src_t, dst, dst_t = dst, dst_t, src, src_t
        if rel not in FACT_EDGES or not src or not dst:
            continue
        attrs = dict(e.get("attributes") or {})
        edge_id = str(attrs.get("edge_id") or synthetic_edge_id(rel, src, dst))
        txn_id = dst if dst_t == "RelatedPartyTxn" else src if src_t == "RelatedPartyTxn" else None
        out.setdefault(
            edge_id,
            Triple(
                edge_id=edge_id,
                rel=rel,
                src_id=src,
                src_type=src_t,
                dst_id=dst,
                dst_type=dst_t,
                attrs=attrs,
                txn=txns.get(txn_id) if txn_id else None,
                hop=hop,
            ),
        )
    return list(out.values())


def filter_fiscal_years(triples: list[Triple], fiscal_years: list[str]) -> list[Triple]:
    """Keep edges from the requested years, plus edges that carry no year at all."""
    if not fiscal_years:
        return triples
    return [t for t in triples if not t.fiscal_year or t.fiscal_year in fiscal_years]


def cap_per_seed(triples: list[Triple], seeds: set[str], fanout: int) -> list[Triple]:
    """At most `fanout` edges per seed, newest fiscal year first. Counterparty
    edges that do not touch a seed ride along with their transaction."""
    by_seed: dict[str, list[Triple]] = defaultdict(list)
    for t in triples:
        for end in t.endpoints():
            if end in seeds:
                by_seed[end].append(t)

    kept: dict[str, Triple] = {}
    for items in by_seed.values():
        items.sort(key=lambda t: (t.fiscal_year, t.edge_id), reverse=True)
        for t in items[:fanout]:
            kept[t.edge_id] = t

    kept_txns = {t.txn_id for t in kept.values() if t.txn_id}
    for t in triples:
        if t.edge_id not in kept and t.txn_id in kept_txns and not (set(t.endpoints()) & seeds):
            kept[t.edge_id] = t
    return list(kept.values())


def frontier_ids(triples: list[Triple], seeds: set[str], hubs: set[str]) -> list[str]:
    """Neighbours worth a second hop: people / companies / audit firms, never the
    seeds again and never hubs."""
    found: dict[str, None] = {}
    for t in triples:
        for end, end_type in ((t.src_id, t.src_type), (t.dst_id, t.dst_type)):
            if end_type in EXPANDABLE_TYPES and end not in seeds and end not in hubs:
                found[end] = None
    return list(found)[:MAX_FRONTIER]


def _call(
    seeds: list[str],
    edge_types: list[str],
    excluded: set[str],
    fanout: int,
    hop: int,
    cfg: GraphRAGConfig,
    tracer: Tracer,
) -> list[Triple]:
    """One expand_hop call; on failure retry once with half the fan-out."""
    last_error = ""
    for attempt_fanout in (fanout, max(1, fanout // RETRY_FANOUT_FACTOR)):
        params = {
            "seed_ids": seeds,
            "edge_types": edge_types,
            "excluded": sorted(excluded) or NO_EXCLUSIONS,
            "max_rows": max(attempt_fanout * len(seeds), attempt_fanout),
        }
        t0 = time.perf_counter()
        try:
            raw = run_installed_strict(QUERY_NAME, params, cfg.gsql_timeout_seconds)
        except GraphQueryError as e:
            last_error = str(e)
            tracer.add(
                "retrieve",
                f"expand_hop(hop {hop})",
                f"{len(seeds)} seeds, fanout={attempt_fanout}",
                "",
                latency_ms=int((time.perf_counter() - t0) * 1000),
                error=last_error,
            )
            continue
        triples = parse_triples(raw, hop)
        tracer.add(
            "retrieve",
            f"expand_hop(hop {hop})",
            f"{len(seeds)} seeds, types={','.join(edge_types)}, fanout={attempt_fanout}",
            f"{len(triples)} triples",
            latency_ms=int((time.perf_counter() - t0) * 1000),
        )
        return triples
    raise ExpansionFailed(last_error)


def expand(
    seeds: list[str],
    relations: RelationChoice,
    fiscal_years: list[str],
    tracer: Tracer,
    cfg: GraphRAGConfig = GRAPHRAG,
    hubs: set[str] | None = None,
) -> list[Triple]:
    """Bounded expansion from the linked entities.

    Hop 1 follows the chosen relation types. Hop 2 starts from hop-1 neighbours
    that are not hubs, follows the same types minus hub relations (unless asked
    for) with a smaller fan-out. Raises ExpansionFailed if the graph cannot be
    queried; returns [] for an empty subgraph."""
    if not seeds:
        return []
    if hubs is None:
        hubs = hub_ids(cfg.hub_degree_percentile, cfg.hub_min_degree)

    seed_set = set(seeds)
    hop1 = _call(seeds, relations.types, set(), cfg.fanout_hop1, 1, cfg, tracer)
    hop1 = cap_per_seed(filter_fiscal_years(hop1, fiscal_years), seed_set, cfg.fanout_hop1)
    all_triples = {t.edge_id: t for t in hop1}

    hop2_types = relations.hop2_types
    if cfg.max_hops >= 2 and hop2_types:
        frontier = frontier_ids(hop1, seed_set, hubs)
        if frontier:
            hop2 = _call(frontier, hop2_types, hubs, cfg.fanout_hop2, 2, cfg, tracer)
            hop2 = cap_per_seed(
                filter_fiscal_years(hop2, fiscal_years), set(frontier), cfg.fanout_hop2
            )
            for t in hop2:
                all_triples.setdefault(t.edge_id, t)

    triples = list(all_triples.values())
    incomplete = incomplete_transactions(triples)
    tracer.add(
        "retrieve",
        "expand",
        f"seeds={len(seeds)} years={fiscal_years or 'any'} hubs_skipped={len(hubs)}",
        f"{len(triples)} triples ({sum(t.hop == 2 for t in triples)} at hop 2)"
        + (f"; {len(incomplete)} transactions missing a counterparty" if incomplete else ""),
    )
    return triples


def incomplete_transactions(triples: list[Triple]) -> list[str]:
    parties: dict[str, set[str]] = defaultdict(set)
    for t in triples:
        if t.txn_id:
            parties[t.txn_id].add(t.edge_id)
    return [txn for txn, edges in parties.items() if len(edges) < 2]
