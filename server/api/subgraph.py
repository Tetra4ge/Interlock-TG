import re

from server.api.schemas import SubgraphEdge, SubgraphNode, SubgraphOut
from server.graph.queries import GraphQueryError, entity_names, run_installed_strict
from server.pipelines.graphrag.expand import parse_triples
from server.pipelines.graphrag.models import Triple
from server.pipelines.graphrag.serialize import format_crore

QUERY_NAME = "subgraph_by_edges"
MAX_EDGE_IDS = 100
EDGE_ID_RE = re.compile(r"[A-Za-z0-9_\-|]{1,64}")
DEFAULT_TIMEOUT_S = 10


class SubgraphUnavailable(RuntimeError):
    """The graph could not be queried; the dashboard shows an explanatory empty state."""


def parse_edge_ids(raw: str) -> list[str]:
    """'a,b,c' -> ['a','b','c']. A transaction's evidence id is itself 'edgeA,edgeB',
    so splitting on commas yields both of its edges. Raises ValueError on a bad id."""
    ids = [part.strip() for part in raw.split(",") if part.strip()]
    if not ids:
        raise ValueError("edge_ids must name at least one edge")
    if len(ids) > MAX_EDGE_IDS:
        raise ValueError(f"at most {MAX_EDGE_IDS} edge ids per request")
    for i in ids:
        if not EDGE_ID_RE.fullmatch(i):
            raise ValueError(f"invalid edge id {i[:20]!r}")
    return list(dict.fromkeys(ids))


def _edge_label(t: Triple) -> str:
    a = t.attrs
    if t.rel == "DIRECTOR_OF" and a.get("role"):
        return str(a["role"])
    if t.rel == "SUBSIDIARY_OF" and a.get("pct_held"):
        return f"{a['pct_held']:g}% held"
    if t.rel == "PARTY_TO" and a.get("side"):
        return f"{a['side']} party"
    return t.rel.replace("_", " ").lower()


def _txn_label(t: Triple) -> str:
    txn = t.txn or {}
    parts = [
        str(txn.get("nature") or "Related-party transaction"),
        format_crore(txn.get("amount_inr")),
    ]
    return " ".join(p for p in parts if p)


def build_subgraph(triples: list[Triple], requested: list[str]) -> SubgraphOut:
    wanted = set(requested)
    kept = [t for t in triples if t.edge_id in wanted]  # never return an edge nobody asked for

    ids = {e for t in kept for e in t.endpoints() if e.startswith(("C:", "P:", "A:"))}
    names = entity_names(sorted(ids))

    nodes: dict[str, SubgraphNode] = {}
    for t in kept:
        for end, end_type in ((t.src_id, t.src_type), (t.dst_id, t.dst_type)):
            if end in nodes:
                continue
            label = _txn_label(t) if end_type == "RelatedPartyTxn" else names.get(end, (end, ""))[0]
            nodes[end] = SubgraphNode(id=end, type=end_type, label=label)

    edges = [
        SubgraphEdge(
            id=t.edge_id,
            type=t.rel,
            source=t.src_id,
            target=t.dst_id,
            label=_edge_label(t),
            fiscal_year=t.fiscal_year,
            doc_id=t.doc_id,
            page=t.page,
            quote=t.quote,
        )  # fmt: skip
        for t in kept
    ]
    return SubgraphOut(
        nodes=list(nodes.values()), edges=edges, requested=len(requested), found=len(edges)
    )


def fetch_subgraph(edge_ids: list[str], timeout_s: int = DEFAULT_TIMEOUT_S) -> SubgraphOut:
    try:
        raw = run_installed_strict(QUERY_NAME, {"edge_ids": edge_ids}, timeout_s)
    except GraphQueryError as e:
        raise SubgraphUnavailable(str(e)[:300]) from e
    return build_subgraph(parse_triples(raw, hop=1), edge_ids)
