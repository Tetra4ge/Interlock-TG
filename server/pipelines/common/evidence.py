from server.pipelines.models import EvidenceItem


def chunk_evidence(hits: list[dict]) -> tuple[list[EvidenceItem], dict[str, dict]]:
    """Retrieved chunk dicts -> evidence items plus the provenance map the shared
    labelling and citation steps use."""
    provenance = {
        h["chunk_id"]: {
            "doc_id": h.get("doc_id", ""),
            "page_start": h.get("page_start", 0),
            "page_end": h.get("page_end", 0),
            "section": h.get("section", ""),
            "fiscal_year": h.get("fiscal_year", ""),
        }
        for h in hits
    }
    items = [EvidenceItem(kind="chunk", ref_id=h["chunk_id"], text=h.get("text", "")) for h in hits]
    return items, provenance
