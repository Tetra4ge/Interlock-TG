import json
from datetime import date

import pytest

from server.extract.schemas import (
    AuditorRecord,
    DirectorRecord,
    Evidence,
    RelatedPartyTxnRecord,
)
from server.graph import loader


class FakeTG:
    """Captures what the loader would upsert into TigerGraph."""

    def __init__(self) -> None:
        self.vertices: dict[str, list[tuple]] = {}
        self.edges: dict[tuple[str, str, str], list[tuple]] = {}

    def upsertVertices(self, v_type: str, rows: list[tuple]) -> None:  # noqa: N802
        self.vertices.setdefault(v_type, []).extend(rows)

    def upsertEdges(  # noqa: N802
        self, src: str, e_type: str, tgt: str, rows: list[tuple]
    ) -> None:
        self.edges.setdefault((src, e_type, tgt), []).extend(rows)


EVIDENCE = Evidence(doc_id="doc1", page=46, quote="Mr. O P Bhatt | Independent Director")


def _seed(db, record_type: str, record, mentions: dict[str, str]) -> None:
    db.execute(
        "INSERT OR IGNORE INTO documents (doc_id, company_id, doc_type, fiscal_year, "
        "file_path, fetched_at, status) VALUES ('doc1', 'TATASTEEL', 'annual_report', "
        "'FY2023-24', 'x.pdf', 'now', 'extracted')"
    )
    db.execute(
        "INSERT INTO records (record_id, run_id, doc_id, record_type, payload_json, status) "
        "VALUES (?, 'run1', 'doc1', ?, ?, 'accepted')",
        ["rec1", record_type, record.model_dump_json()],
    )
    for role, entity_id in mentions.items():
        kind = {"P": "person", "C": "company", "A": "audit_firm"}[entity_id[0]]
        db.execute(
            "INSERT OR IGNORE INTO entities (entity_id, kind, canonical_name, aliases_text) "
            "VALUES (?, ?, ?, '')",
            [entity_id, kind, entity_id],
        )
        db.execute(
            "INSERT INTO merge_log (mention_id, entity_id, method, score) VALUES (?, ?, 'x', 100)",
            [f"rec1:{role}", entity_id],
        )


@pytest.fixture
def tg(memdb, monkeypatch: pytest.MonkeyPatch) -> FakeTG:
    fake = FakeTG()
    monkeypatch.setattr(loader, "get_tg_connection", lambda: fake)
    monkeypatch.setattr(loader, "connect", lambda: memdb)
    return fake


def test_director_edge_carries_provenance_and_dates(tg, memdb) -> None:
    _seed(
        memdb,
        "directors",
        DirectorRecord(
            person_name="O P Bhatt",
            din="00548091",
            company_name="Tata Steel Limited",
            role="Independent Director",
            is_independent=True,
            appointed_on=date(2023, 6, 1),
            fiscal_year="FY2023-24",
            evidence=EVIDENCE,
        ),
        {"person": "P:00548091", "context_company": "C:TATASTEEL"},
    )

    loader.load_graph("run1")

    ((src, tgt, attrs),) = tg.edges[("Person", "DIRECTOR_OF", "Company")]
    assert (src, tgt) == ("P:00548091", "C:TATASTEEL")
    assert attrs["page"] == 46 and attrs["quote"] == EVIDENCE.quote
    assert attrs["doc_id"] == "doc1" and attrs["run_id"] == "run1"
    assert attrs["start_date"] == "2023-06-01" and attrs["fiscal_year"] == "FY2023-24"
    assert attrs["independent"] is True


def test_rpt_keeps_its_rupee_amount_and_provenance(tg, memdb) -> None:
    _seed(
        memdb,
        "rpt",
        RelatedPartyTxnRecord(
            reporting_company="Tata Steel Limited",
            counterparty_name="Tata Sons Private Limited",
            relationship="Promoter",
            nature="Dividend paid",
            amount_inr=125_000_000.0,
            amount_raw="12.5 (₹ crore)",
            fiscal_year="FY2023-24",
            evidence=EVIDENCE,
        ),
        {"context_company": "C:TATASTEEL", "counterparty": "C:xabc"},
    )

    loader.load_graph("run1")

    ((_txn_id, attrs),) = tg.vertices["RelatedPartyTxn"]
    assert attrs["amount_inr"] == 125_000_000.0
    sides = {a["side"]: a for _s, _t, a in tg.edges[("Company", "PARTY_TO", "RelatedPartyTxn")]}
    assert set(sides) == {"reporting", "counterparty"}
    assert all(a["page"] == 46 and a["quote"] == EVIDENCE.quote for a in sides.values())


def test_auditor_edge_carries_provenance(tg, memdb) -> None:
    _seed(
        memdb,
        "auditor",
        AuditorRecord(
            company_name="Tata Steel Limited",
            firm_name="Price Waterhouse & Co Chartered Accountants LLP",
            firm_registration_no="304026E",
            fiscal_year="FY2023-24",
            evidence=EVIDENCE,
        ),
        {"context_company": "C:TATASTEEL", "audit_firm": "A:304026E"},
    )

    loader.load_graph("run1")

    ((src, tgt, attrs),) = tg.edges[("Company", "AUDITED_BY", "AuditFirm")]
    assert (src, tgt) == ("C:TATASTEEL", "A:304026E")
    assert attrs["page"] == 46 and attrs["doc_id"] == "doc1"
    assert attrs["fiscal_year"] == "FY2023-24" and attrs["run_id"] == "run1"


def test_chunks_are_loaded_from_disk(tg, memdb, tmp_path, monkeypatch) -> None:
    _seed(
        memdb,
        "auditor",
        AuditorRecord(company_name="x", firm_name="y", fiscal_year="FY2023-24", evidence=EVIDENCE),
        {"context_company": "C:TATASTEEL", "audit_firm": "A:1"},
    )
    chunk = {
        "chunk_id": "doc1-governance-0001",
        "text": "t",
        "section": "governance",
        "page_start": 1,
        "page_end": 2,
        "fiscal_year": "FY2023-24",
        "company_id": "TATASTEEL",
    }
    (tmp_path / "doc1_chunks.json").write_text(json.dumps([chunk]))
    monkeypatch.setattr(loader, "CHUNKS_DIR", tmp_path)

    loader.load_graph("run1")

    ((cid, attrs),) = tg.vertices["Chunk"]
    assert cid == "doc1-governance-0001" and attrs["doc_id"] == "doc1"
    assert tg.edges[("Document", "HAS_CHUNK", "Chunk")] == [("doc1", cid, {})]


def test_subsidiary_edge_is_loaded_with_provenance(tg, memdb) -> None:
    from server.extract.schemas import SubsidiaryRecord

    _seed(
        memdb,
        "subsidiaries",
        SubsidiaryRecord(
            parent_company="Tata Steel Limited",
            subsidiary_name="Tata Steel Downstream Products Limited",
            pct_held=100.0,
            evidence=EVIDENCE,
        ),
        {"context_company": "C:TATASTEEL", "subsidiary": "C:xsub"},
    )

    loader.load_graph("run1")

    ((src, tgt, attrs),) = tg.edges[("Company", "SUBSIDIARY_OF", "Company")]
    assert (src, tgt) == ("C:xsub", "C:TATASTEEL")  # subsidiary -> parent
    assert attrs["pct_held"] == 100.0
    assert attrs["page"] == 46 and attrs["doc_id"] == "doc1" and attrs["run_id"] == "run1"
