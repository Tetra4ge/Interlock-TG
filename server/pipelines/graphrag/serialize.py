from typing import Any

from server.pipelines.graphrag.models import Triple
from server.pipelines.models import EvidenceItem

RUPEES_PER_CRORE = 1e7
DOC_PREFIX_CHARS = 12


def _entity(entity_id: str, vertex_type: str, names: dict[str, tuple[str, str]]) -> str:
    name = names.get(entity_id, (entity_id, ""))[0]
    return f"{vertex_type}: {name}"


def format_crore(amount_inr: Any) -> str:
    try:
        value = float(amount_inr)
    except (TypeError, ValueError):
        return ""
    return f"₹ {value / RUPEES_PER_CRORE:,.2f} crore"


def _source_line(t: Triple) -> str:
    if not t.doc_id:
        return "  source: not recorded for this relation"
    doc = f"{t.doc_id[:DOC_PREFIX_CHARS]}…"
    quote = f' | quote: "{t.quote}"' if t.quote else ""
    return f"  source: doc {doc}, p.{t.page}{quote}"


def _joined(*parts: str) -> str:
    return "; ".join(p for p in parts if p)


def _relation_label(t: Triple) -> str:
    a = t.attrs
    if t.rel == "DIRECTOR_OF":
        tenure = ""
        if a.get("start_date") or a.get("end_date"):
            tenure = f"{a.get('start_date') or '?'} to {a.get('end_date') or 'present'}"
        return "DIRECTOR_OF: " + _joined(
            str(a.get("role") or ""),
            "independent" if a.get("independent") else "",
            t.fiscal_year,
            tenure,
        )
    if t.rel == "AUDITED_BY":
        return "AUDITED_BY: " + _joined(t.fiscal_year)
    if t.rel == "SUBSIDIARY_OF":
        pct = f"{a['pct_held']:g}% held" if a.get("pct_held") else ""
        return "SUBSIDIARY_OF: " + _joined(pct, f"as of {a['as_of']}" if a.get("as_of") else "")
    if t.rel == "HOLDS_STAKE":
        pledged = f"{a['pledged_pct']:g}% pledged" if a.get("pledged_pct") else ""
        return "HOLDS_STAKE: " + _joined(pledged)
    return t.rel


def _plain_line(t: Triple, names: dict[str, tuple[str, str]]) -> str:
    label = _relation_label(t).rstrip(": ")
    return (
        f"{_entity(t.src_id, t.src_type, names)} —[{label}]→ "
        f"{_entity(t.dst_id, t.dst_type, names)}\n{_source_line(t)}"
    )


def _txn_line(group: list[Triple], names: dict[str, tuple[str, str]]) -> str:
    def party(t: Triple) -> str:
        return (
            _entity(t.src_id, t.src_type, names)
            if t.src_type != "RelatedPartyTxn"
            else _entity(t.dst_id, t.dst_type, names)
        )

    reporting = next((t for t in group if t.attrs.get("side") == "reporting"), None)
    counter = next((t for t in group if t.attrs.get("side") == "counterparty"), None)
    first = group[0]
    txn = first.txn or {}
    label = "RELATED-PARTY TXN " + first.fiscal_year if first.fiscal_year else "RELATED-PARTY TXN"
    detail = _joined(str(txn.get("nature") or ""), format_crore(txn.get("amount_inr")))
    relationship = f" (relationship: {txn['relationship']})" if txn.get("relationship") else ""
    left = party(reporting) if reporting else party(first)
    right = party(counter) if counter else "(counterparty not retrieved)"
    return f"{left} —[{label}: {detail}]→ {right}{relationship}\n{_source_line(first)}"


def serialize(
    triples: list[Triple], names: dict[str, tuple[str, str]]
) -> tuple[list[EvidenceItem], dict[str, dict]]:
    """One evidence item per triple, or per transaction (both parties together).
    Returns the items plus the provenance map the shared label/citation step needs."""
    items: list[EvidenceItem] = []
    provenance: dict[str, dict] = {}
    done_txns: set[str] = set()

    for t in triples:
        if t.txn_id:
            if t.txn_id in done_txns:
                continue
            done_txns.add(t.txn_id)
            group = [x for x in triples if x.txn_id == t.txn_id]
            text = _txn_line(group, names)
            ref = ",".join(x.edge_id for x in group)
        else:
            text = _plain_line(t, names)
            ref = t.edge_id
        items.append(EvidenceItem(kind="triple", ref_id=ref, text=text))
        provenance[ref] = {
            "doc_id": t.doc_id,
            "page_start": t.page,
            "page_end": t.page,
            "section": t.rel,
            "fiscal_year": t.fiscal_year,
        }
    return items, provenance
