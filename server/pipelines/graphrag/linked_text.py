import time
from typing import Any

from server.embed.index import score_chunks
from server.graph.queries import GraphQueryError, chunks_for_entities_strict
from server.pipelines.common.rerank import rerank_fused
from server.pipelines.common.result import elapsed_ms
from server.pipelines.common.tracer import Tracer
from server.pipelines.config import GRAPHRAG, RETRIEVAL, GraphRAGConfig
from server.pipelines.graphrag.models import Triple

ENTITY_PREFIXES = ("C:", "P:", "A:")
MAX_ENTITIES = 50
CANDIDATE_LIMIT = 50


def entity_ids_for_text(linked_ids: list[str], triples: list[Triple]) -> list[str]:
    """Linked entities first, then their hop-1 neighbours (fact entities only:
    no transactions, sectors or chunks), capped to keep the query small."""
    found: dict[str, None] = {i: None for i in linked_ids if i.startswith(ENTITY_PREFIXES)}
    for t in triples:
        if t.hop != 1:
            continue
        for end in t.endpoints():
            if end.startswith(ENTITY_PREFIXES):
                found.setdefault(end, None)
    return list(found)[:MAX_ENTITIES]


def parse_chunks(raw: Any) -> list[dict]:
    """[{"Chunks": [{"v_id", "attributes": {...}}]}] -> the chunk dicts the RAG
    path produces, so both feed the same evidence builder."""
    chunks: list[dict] = []
    for block in raw if isinstance(raw, list) else []:
        if not isinstance(block, dict):
            continue
        for v in block.get("Chunks") or []:
            if not isinstance(v, dict):
                continue
            attrs = v.get("attributes") or {}
            if v.get("v_id") and attrs.get("text"):
                chunks.append({"chunk_id": str(v["v_id"]), **attrs})
    return chunks


def linked_text(
    question: str,
    entity_ids: list[str],
    fiscal_years: list[str],
    excluded_docs: set[str],
    tracer: Tracer,
    cfg: GraphRAGConfig = GRAPHRAG,
) -> list[dict]:
    """Chunks that mention the linked entities or their neighbours, ranked by
    similarity to the question (and reranked if RAG reranks). Never raises: the
    triples can still answer the question without supporting text."""
    if not entity_ids:
        return []
    t0 = time.perf_counter()
    try:
        raw = chunks_for_entities_strict(entity_ids, CANDIDATE_LIMIT, cfg.gsql_timeout_seconds)
        chunks = parse_chunks(raw)
    except GraphQueryError as e:
        tracer.add(
            "retrieve",
            "linked_text",
            f"{len(entity_ids)} entities",
            "",
            latency_ms=elapsed_ms(t0),
            error=str(e),
        )
        return []

    chunks = [c for c in chunks if c.get("doc_id") not in excluded_docs]
    if fiscal_years:
        chunks = [c for c in chunks if not c.get("fiscal_year") or c["fiscal_year"] in fiscal_years]

    try:
        scores = score_chunks(question, [c["chunk_id"] for c in chunks])
    except FileNotFoundError as e:
        tracer.add("retrieve", "linked_text", question, "", error=str(e))
        return []
    chunks = [c for c in chunks if c["chunk_id"] in scores]
    chunks.sort(key=lambda c: (-scores[c["chunk_id"]], c["chunk_id"]))

    if RETRIEVAL.use_reranker and chunks:
        chunks = rerank_fused(question, chunks, cfg.linked_chunks)
    chunks = chunks[: cfg.linked_chunks]

    tracer.add(
        "retrieve",
        "linked_text",
        f"{len(entity_ids)} entities, years={fiscal_years or 'any'}",
        ", ".join(c["chunk_id"] for c in chunks),
        latency_ms=elapsed_ms(t0),
    )
    return chunks
