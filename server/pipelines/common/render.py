from pydantic import BaseModel

from server.pipelines.models import EvidenceItem


class LabeledEvidence(BaseModel):
    """An EvidenceItem plus the provenance needed to resolve a citation back
    to a real (doc_id, page) -- kept out of EvidenceItem itself since that
    model is shared with GraphRAG/agent evidence kinds that carry different
    provenance (edges, tool results)."""

    label: str
    item: EvidenceItem
    doc_id: str
    page_start: int
    page_end: int
    section: str = ""
    fiscal_year: str = ""


def assign_labels(
    items: list[EvidenceItem], provenance: dict[str, dict]
) -> dict[str, LabeledEvidence]:
    """Stable E1..En labels in the given (priority) order. `provenance` maps
    an item's ref_id to its doc_id/page_start/page_end/section/fiscal_year."""
    labels: dict[str, LabeledEvidence] = {}
    for i, item in enumerate(items, start=1):
        label = f"E{i}"
        prov = provenance.get(item.ref_id, {})
        labels[label] = LabeledEvidence(
            label=label,
            item=item,
            doc_id=prov.get("doc_id", ""),
            page_start=prov.get("page_start", 0),
            page_end=prov.get("page_end", 0),
            section=prov.get("section", ""),
            fiscal_year=prov.get("fiscal_year", ""),
        )
    return labels


def render_blocks(labels: dict[str, LabeledEvidence]) -> str:
    """Every evidence item shown to the model with a short label and its
    provenance, e.g.:

    [E1] (chunk | doc 3f2a1c9d…, pages 45-46 | FY2023-24 | related_party)
    <chunk text>
    """
    blocks = []
    for label, le in labels.items():
        doc_ref = f"{le.doc_id[:12]}…" if le.doc_id else "unknown"
        meta = [f"doc {doc_ref}", f"pages {le.page_start}-{le.page_end}"]
        if le.fiscal_year:
            meta.append(le.fiscal_year)
        if le.section:
            meta.append(le.section)
        header = f"[{label}] ({le.item.kind} | {' | '.join(meta)})"
        blocks.append(f"{header}\n{le.item.text}")
    return "\n\n".join(blocks)
