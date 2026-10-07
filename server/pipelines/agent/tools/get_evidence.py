import re

from pydantic import BaseModel, Field

from server.embed.keyword import load_chunks
from server.graph.queries import GraphQueryError, run_installed_strict
from server.pipelines.agent.tools.base import ToolContext, ToolResult, error
from server.pipelines.agent.tools.neighbors import log_triples
from server.pipelines.graphrag.expand import parse_triples

DESCRIPTION = (
    "Get the full text and source page of an evidence item you were shown, by its label "
    "(for example E5). Search results are only previews; use this to read the rest of one "
    "before relying on it or citing it. Also accepts a fact's ref_id."
)


LABEL = re.compile(r"E\d+")


class GetEvidenceArgs(BaseModel):
    ref_id: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_:\-|,]+$")


def _from_log(ctx: ToolContext, ref_id: str) -> ToolResult | None:
    label = ref_id.upper() if LABEL.fullmatch(ref_id.upper()) else ctx.log.label_of(ref_id)
    item = ctx.log.item_for_label(label) if label else None
    if label is None or item is None:
        return None
    prov = ctx.log.provenance.get(item.ref_id, {})
    where = f" (doc {prov.get('doc_id', '')[:12]}, p.{prov.get('page_start', 0)})"
    return ToolResult(ok=True, text=f"[{label}]{where}\n{item.text}", labels=[label])


def run(ctx: ToolContext, args: GetEvidenceArgs) -> ToolResult:
    ref_id = args.ref_id
    found = _from_log(ctx, ref_id)
    if found:
        return found

    if "-" in ref_id and "," not in ref_id:  # chunk ids look like "<doc12>-<n>"
        chunk = next((c for c in load_chunks(None) if str(c.get("chunk_id")) == ref_id), None)
        if chunk is None:
            return error(f"unknown ref_id {ref_id!r}")
        label = ctx.log.add(
            "chunk", ref_id, chunk.get("text", ""), chunk.get("doc_id", ""),
            chunk.get("page_start", 0), chunk.get("page_end", 0), chunk.get("section", ""),
            chunk.get("fiscal_year", ""),
        )  # fmt: skip
        return ToolResult(ok=True, text=f"[{label}] {chunk.get('text', '')}", labels=[label])

    try:
        raw = run_installed_strict(
            "get_edge_by_id", {"edge_id": ref_id}, ctx.cfg.gsql_timeout_seconds
        )
    except GraphQueryError as e:
        return error(f"the graph could not be queried ({str(e)[:200]})")
    triples = parse_triples(_as_edge_blocks(raw), hop=1)
    if not triples:
        return error(f"unknown ref_id {ref_id!r}")
    return log_triples(ctx, triples, set(), set(), len(triples), [])


def _as_edge_blocks(raw: object) -> list[dict]:
    """get_edge_by_id prints a bare edge list; parse_triples expects named blocks."""
    blocks = raw if isinstance(raw, list) else []
    edges = [
        e
        for b in blocks
        if isinstance(b, dict)
        for v in b.values()
        if isinstance(v, list)
        for e in v
    ]
    return [{"edges": edges}]
