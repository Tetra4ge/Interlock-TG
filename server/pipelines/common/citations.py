import json
from pathlib import Path

from rapidfuzz import fuzz

from server.pipelines.common.render import LabeledEvidence
from server.pipelines.models import Citation, ModelCitation

PARSED_DIR = Path("data/parsed")
QUOTE_MATCH_THRESHOLD = 95  # rapidfuzz partial_ratio


def _load_pages(doc_id: str) -> list[dict]:
    parsed_file = PARSED_DIR / f"{doc_id}.json"
    if not parsed_file.exists():
        return []
    return json.loads(parsed_file.read_text()).get("pages", [])


def _quote_matches(evidence_text: str, quote: str) -> bool:
    if not quote:
        return False
    if quote in evidence_text:
        return True
    return fuzz.partial_ratio(quote, evidence_text) >= QUOTE_MATCH_THRESHOLD


def _resolve_page(doc_id: str, page_start: int, page_end: int, quote: str) -> int:
    """Pick the page within page_start..page_end whose text contains the
    quote; falls back to page_start if no page matches (e.g. parsed JSON
    missing, or the quote was flagged as not-found in the first place)."""
    for page in _load_pages(doc_id):
        page_no = page.get("page_no")
        if page_no is None or not (page_start <= page_no <= page_end):
            continue
        text = page.get("cleaned_text", page.get("text", ""))
        if quote and quote in text:
            return page_no
    return page_start


def validate_citations(
    citations: list[ModelCitation], labels: dict[str, LabeledEvidence]
) -> tuple[list[Citation], dict[str, int]]:
    """Per phase-04 Step 8: an unknown evidence_id is dropped and flagged; a
    quote that doesn't appear in its evidence block is kept but flagged; a
    valid citation is resolved to a real (doc_id, page, quote). Returns the
    resolved citations plus flag counts for the trace / faithfulness metric."""
    resolved: list[Citation] = []
    flags = {"invalid_citation_label": 0, "quote_not_found": 0}

    for c in citations:
        le = labels.get(c.evidence_id)
        if le is None:
            flags["invalid_citation_label"] += 1
            continue

        if not _quote_matches(le.item.text, c.quote):
            flags["quote_not_found"] += 1

        page = _resolve_page(le.doc_id, le.page_start, le.page_end, c.quote)
        resolved.append(Citation(doc_id=le.doc_id, page=page, quote=c.quote))

    return resolved, flags
