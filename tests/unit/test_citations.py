import json
from pathlib import Path

import pytest

from server.pipelines.common import citations as citations_mod
from server.pipelines.common.citations import validate_citations
from server.pipelines.common.render import LabeledEvidence
from server.pipelines.models import EvidenceItem, ModelCitation


def _labeled(
    label: str, doc_id: str, text: str, page_start: int = 1, page_end: int = 1
) -> LabeledEvidence:
    return LabeledEvidence(
        label=label,
        item=EvidenceItem(kind="chunk", ref_id=f"chunk-{label}", text=text),
        doc_id=doc_id,
        page_start=page_start,
        page_end=page_end,
    )


def test_unknown_label_dropped_and_flagged() -> None:
    labels = {"E1": _labeled("E1", "doc1", "the auditor is Deloitte")}
    citations, flags = validate_citations(
        [ModelCitation(evidence_id="E9", quote="the auditor is Deloitte")], labels
    )

    assert citations == []
    assert flags["invalid_citation_label"] == 1
    assert flags["quote_not_found"] == 0


def test_quote_missing_kept_but_flagged() -> None:
    labels = {"E1": _labeled("E1", "doc1", "the auditor is Deloitte")}
    citations, flags = validate_citations(
        [ModelCitation(evidence_id="E1", quote="totally unrelated text")], labels
    )

    assert len(citations) == 1
    assert flags["quote_not_found"] == 1


def test_valid_citation_resolved() -> None:
    labels = {"E1": _labeled("E1", "doc1", "the auditor is Deloitte")}
    citations, flags = validate_citations(
        [ModelCitation(evidence_id="E1", quote="the auditor is Deloitte")], labels
    )

    assert len(citations) == 1
    assert citations[0].doc_id == "doc1"
    assert citations[0].quote == "the auditor is Deloitte"
    assert flags == {"invalid_citation_label": 0, "quote_not_found": 0}


def test_page_resolution_picks_page_containing_quote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(citations_mod, "PARSED_DIR", tmp_path)
    doc_id = "doc-45-46"
    (tmp_path / f"{doc_id}.json").write_text(
        json.dumps(
            {
                "pages": [
                    {"page_no": 45, "cleaned_text": "nothing relevant here"},
                    {"page_no": 46, "cleaned_text": "the auditor is Deloitte Haskins"},
                ]
            }
        )
    )
    labels = {
        "E1": _labeled("E1", doc_id, "the auditor is Deloitte Haskins", page_start=45, page_end=46)
    }

    citations, flags = validate_citations(
        [ModelCitation(evidence_id="E1", quote="the auditor is Deloitte Haskins")], labels
    )

    assert citations[0].page == 46
    assert flags["quote_not_found"] == 0


def test_page_resolution_falls_back_to_page_start_when_parsed_json_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(citations_mod, "PARSED_DIR", tmp_path)
    labels = {"E1": _labeled("E1", "missing-doc", "some text", page_start=12, page_end=13)}

    citations, _ = validate_citations([ModelCitation(evidence_id="E1", quote="some text")], labels)

    assert citations[0].page == 12


def test_empty_citations_list() -> None:
    citations, flags = validate_citations([], {})
    assert citations == []
    assert flags == {"invalid_citation_label": 0, "quote_not_found": 0}
