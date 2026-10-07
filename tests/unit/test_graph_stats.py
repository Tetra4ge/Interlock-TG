import json

import pytest

from server.graph import stats
from tests.conftest import MemoryDB


def _doc(db: MemoryDB, doc_id: str, company: str, fy: str) -> None:
    db.execute(
        "INSERT INTO documents (doc_id, company_id, doc_type, fiscal_year, file_path, fetched_at) "
        "VALUES (?, ?, 'annual_report', ?, 'x.pdf', 'now')",
        [doc_id, company, fy],
    )


def _rec(
    db: MemoryDB, rid: str, doc: str, rtype: str, payload: dict, status: str = "accepted"
) -> None:
    db.execute(
        "INSERT INTO records (record_id, run_id, doc_id, record_type, payload_json, status) "
        "VALUES (?, 'run-1', ?, ?, ?, ?)",
        [rid, doc, rtype, json.dumps(payload), status],
    )


def _person(db: MemoryDB, rid: str, entity_id: str, name: str) -> None:
    db.execute(
        "INSERT OR IGNORE INTO entities (entity_id, kind, canonical_name, aliases_text) "
        "VALUES (?, 'person', ?, '')",
        [entity_id, name],
    )
    db.execute(
        "INSERT INTO merge_log (mention_id, entity_id, method) VALUES (?, ?, 'exact_name')",
        [f"{rid}:person", entity_id],
    )


@pytest.fixture
def db(memdb: MemoryDB, monkeypatch: pytest.MonkeyPatch) -> MemoryDB:
    monkeypatch.setattr(stats, "connect", lambda: memdb)
    db_ = memdb
    db_.execute("INSERT INTO extraction_runs (run_id) VALUES ('run-1')")
    _doc(db_, "d-steel", "TATASTEEL", "FY2023-24")
    _doc(db_, "d-motors", "TATAMOTORS", "FY2023-24")
    _doc(db_, "d-fin-22", "BAJAJFINSV", "FY2021-22")
    _doc(db_, "d-fin-23", "BAJAJFINSV", "FY2022-23")

    _rec(db_, "r1", "d-steel", "directors", {"name": "N. Chandrasekaran", "is_independent": False})
    _rec(db_, "r2", "d-steel", "directors", {"name": "Ind One", "is_independent": True})
    _rec(db_, "r3", "d-motors", "directors", {"name": "N. Chandrasekaran", "is_independent": False})
    _rec(db_, "r4", "d-motors", "directors", {"name": "Rejected Person"}, status="rejected")
    _person(db_, "r1", "P:cs", "N. Chandrasekaran")
    _person(db_, "r2", "P:ind", "Ind One")
    _person(db_, "r3", "P:cs", "N. Chandrasekaran")

    _rec(
        db_,
        "a1",
        "d-fin-22",
        "auditor",
        {"firm_name": "Khimji Kunverji & Co LLP", "fiscal_year": "FY2021-22"},
    )
    _rec(
        db_,
        "a2",
        "d-fin-23",
        "auditor",
        {"firm_name": "KKC & Associates LLP", "fiscal_year": "FY2022-23"},
    )
    _rec(db_, "s1", "d-fin-23", "subsidiaries", {"subsidiary_name": "Bajaj Finserv Direct Ltd."})
    _rec(db_, "t1", "d-steel", "rpt", {"amount_inr": 482000000.0, "fiscal_year": "FY2023-24"})
    _rec(db_, "t2", "d-steel", "rpt", {"amount_inr": 18000000.0, "fiscal_year": "FY2023-24"})
    db_.commit()
    return db_


def _texts(topic: str | None = None) -> list[str]:
    return [i.text for i in stats.dataset_stats_pack() if topic is None or i.topic == topic]


def test_coverage_item_states_the_scope_of_the_figures(db: MemoryDB) -> None:
    coverage = next(i for i in stats.dataset_stats_pack() if i.topic == "COVERAGE")
    assert "4 documents" in coverage.text and "3 companies" in coverage.text
    assert "only reflect these companies" in coverage.text


def test_board_sizes_count_only_accepted_records(db: MemoryDB) -> None:
    text = " ".join(_texts("DIRECTOR_OF"))
    assert (
        "Tata Steel Limited had 2 directors on record in FY2023-24, of whom 1 are independent"
        in text
    )
    assert "Tata Motors Limited had 1 director on record" in text  # the rejected one is excluded


def test_a_person_on_two_boards_is_reported(db: MemoryDB) -> None:
    text = " ".join(_texts("DIRECTOR_OF"))
    assert (
        "N. Chandrasekaran sits on 2 boards in the dataset: Tata Motors Limited, Tata Steel Limited"
        in text
    )


def test_no_interlock_is_stated_explicitly(db: MemoryDB) -> None:
    db.execute("DELETE FROM merge_log WHERE mention_id = 'r3:person'")
    db.commit()
    assert any("No person appears on more than one" in t for t in _texts("DIRECTOR_OF"))


def test_auditor_changes_are_detected_between_years(db: MemoryDB) -> None:
    text = " ".join(_texts("AUDITED_BY"))
    assert (
        "Bajaj Finserv Limited's statutory auditor in FY2021-22: Khimji Kunverji & Co LLP" in text
    )
    assert (
        "Bajaj Finserv Limited changed its statutory auditor between FY2021-22 and FY2022-23"
        in text
    )


def test_related_party_totals_are_in_crore(db: MemoryDB) -> None:
    text = " ".join(_texts("PARTY_TO"))
    assert "2 related-party transactions in FY2023-24 totalling ₹ 50.00 crore" in text


def test_singular_and_plural_agree(db: MemoryDB) -> None:
    assert any("listed 1 subsidiary in FY2022-23" in t for t in _texts("SUBSIDIARY_OF"))


def test_sector_lines_separate_tracked_from_extracted(db: MemoryDB) -> None:
    text = " ".join(_texts("IN_SECTOR"))
    assert (
        "Sector Metals & Mining: 1 company tracked (Tata Steel Limited); 1 with extracted records"
        in text
    )
    assert (
        "Sector Power: 1 company tracked (The Tata Power Company Limited); "
        "0 with extracted records." in text
    )


def test_every_item_states_its_basis(db: MemoryDB) -> None:
    pack = stats.dataset_stats_pack()
    assert pack and all("computed from" in i.text and "run-1" in i.text for i in pack)


def test_empty_store_gives_an_empty_pack(memdb: MemoryDB, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stats, "connect", lambda: memdb)
    assert stats.dataset_stats_pack() == []


# --- hubs ----------------------------------------------------------------


def _degrees(db: MemoryDB, counts: dict[str, int]) -> None:
    n = 0
    for entity, count in counts.items():
        for _ in range(count):
            n += 1
            db.execute(
                "INSERT INTO merge_log (mention_id, entity_id, method) VALUES (?, ?, 'exact_name')",
                [f"m{n}:x", entity],
            )
    db.commit()


def test_hubs_are_above_both_the_percentile_and_the_floor(
    memdb: MemoryDB, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(stats, "connect", lambda: memdb)
    _degrees(memdb, {**{f"P:{i}": 2 for i in range(98)}, "A:big": 60, "C:mid": 30})
    assert stats.hub_ids(99, min_degree=25) == {"A:big"}


def test_the_floor_stops_small_graphs_flagging_their_busiest_entity(
    memdb: MemoryDB, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(stats, "connect", lambda: memdb)
    _degrees(memdb, {"C:1": 9, "P:1": 3, "P:2": 2})
    assert stats.hub_ids(99, min_degree=25) == set()


def test_hubs_of_an_empty_store(memdb: MemoryDB, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stats, "connect", lambda: memdb)
    assert stats.hub_ids(99, 25) == set()
