import time
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from server.graph.queries import vector_search
from server.pipelines.agent.tools.base import ToolContext, ToolResult, error
from server.pipelines.common.rerank import rerank_fused
from server.pipelines.config import RETRIEVAL

DESCRIPTION = (
    "Semantic search over the filings' text. Use for facts not in the graph or to confirm "
    "details. Filter by company_id (e.g. C:TATASTEEL or TATASTEEL), fiscal_year (FY2023-24) "
    "and section."
)
PREVIEW_CHARS = 1200  # per chunk shown to the model; the evidence log keeps the full text
DOC_PREFIX_CHARS = 12

Section = Literal[
    "governance", "related_party", "auditor", "board_report", "subsidiaries", "shareholding"
]


def _bare_company_id(value: str | None) -> str | None:
    if value is None:
        return None
    return value.removeprefix("C:").upper()


class SearchTextArgs(BaseModel):
    query: str = Field(min_length=1, max_length=300)
    # Accepts the id exactly as find_entity prints it (C:TATASTEEL) or bare (TATASTEEL);
    # a model naturally reuses the id it was just given.
    company_id: str | None = Field(default=None, pattern=r"^(C:)?[A-Za-z0-9\-]{1,32}$")
    fiscal_year: str | None = Field(default=None, pattern=r"^FY\d{4}-\d{2}$")
    section: Section | None = None
    k: int = Field(default=5, ge=1, le=8)

    @field_validator("company_id")
    @classmethod
    def _strip_prefix(cls, v: str | None) -> str | None:
        return _bare_company_id(v)


def _excluded_doc_ids() -> set[str]:
    from server.pipelines.rag import _excluded_doc_ids

    return _excluded_doc_ids()


def run(ctx: ToolContext, args: SearchTextArgs) -> ToolResult:
    t0 = time.perf_counter()
    k = min(args.k, ctx.cfg.search_max_k)
    filters = {
        key: val
        for key, val in (("company_id", args.company_id), ("fiscal_year", args.fiscal_year))
        if val
    }
    excluded = _excluded_doc_ids()
    # Over-fetch so the section filter and exclusions still leave k results.
    hits = [
        h
        for h in vector_search(args.query, k=max(RETRIEVAL.rag_top_k, k * 4), filters=filters)
        if h.get("doc_id") not in excluded
        and (not args.section or h.get("section") == args.section)
    ]
    if RETRIEVAL.use_reranker and hits:
        hits = rerank_fused(args.query, hits, k)
    hits = hits[:k]
    if not hits:
        return error("no matching text found; try different words or fewer filters")

    blocks, labels = [], []
    for h in hits:
        label = ctx.log.add(
            "chunk", h["chunk_id"], h.get("text", ""), h.get("doc_id", ""),
            h.get("page_start", 0), h.get("page_end", 0), h.get("section", ""),
            h.get("fiscal_year", ""),
        )  # fmt: skip
        labels.append(label)
        text = h.get("text", "")
        preview = text if len(text) <= PREVIEW_CHARS else text[:PREVIEW_CHARS] + " ..."
        doc = f"{h.get('doc_id', '')[:DOC_PREFIX_CHARS]}…"
        meta = f"doc {doc}, pages {h.get('page_start', 0)}-{h.get('page_end', 0)}"
        if h.get("fiscal_year"):
            meta += f", {h['fiscal_year']}"
        if h.get("section"):
            meta += f", {h['section']}"
        blocks.append(f"[{label}] ({meta})\n{preview}")
    ctx.tracer.add(
        "retrieve", "search_text", f"{args.query} {filters or ''}", ", ".join(labels),
        latency_ms=int((time.perf_counter() - t0) * 1000),
    )  # fmt: skip
    return ToolResult(ok=True, text="\n\n".join(blocks), labels=labels)
