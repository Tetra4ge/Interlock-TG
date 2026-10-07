from server.pipelines.graphrag.models import Triple
from server.pipelines.graphrag.serialize import format_crore, serialize
from tests.unit.graphrag_fixtures import triple

NAMES = {
    "P:1": ("Anil Kumar Sharma", "person"),
    "C:1": ("Example Industries Ltd", "company"),
    "C:2": ("Example Trading Pvt Ltd", "company"),
    "A:1": ("Deloitte Haskins & Sells LLP", "audit_firm"),
}
DOC = "3f2a1c" + "0" * 18
_SOURCE = {"doc_id": "91bc07" + "0" * 18, "page": 212, "quote": "Example Trading | Sale of goods"}
_TXN = {
    "nature": "Sale of goods",
    "amount_inr": 482000000.0,
    "relationship": "Entity controlled by promoter",
    "fiscal_year": "FY2022-23",
}
_SOURCE = {"doc_id": "91bc07" + "0" * 18, "page": 212, "quote": "Example Trading | Sale of goods"}
_TXN = {
    "nature": "Sale of goods",
    "amount_inr": 482000000.0,
    "relationship": "Entity controlled by promoter",
    "fiscal_year": "FY2022-23",
}


def _txn_party(edge_id: str, who: str, side: str) -> Triple:
    return Triple(
        edge_id=edge_id,
        rel="PARTY_TO",
        src_id=who,
        src_type="Company",
        dst_id="T1",
        dst_type="RelatedPartyTxn",
        attrs={"side": side, **_SOURCE},
        txn=_TXN,
    )  # fmt: skip


def test_director_line_uses_names_and_shows_role_year_and_source() -> None:
    t = triple(
        src="P:1", dst="C:1", edge_id="e1", role="Independent Director", independent=True,
        doc_id=DOC, page=46, quote="Mr. Anil Kumar Sharma | Independent Director | 01234567",
    )  # fmt: skip
    items, prov = serialize([t], NAMES)
    text = items[0].text
    assert text.startswith(
        "Person: Anil Kumar Sharma \u2014"
        "[DIRECTOR_OF: Independent Director; independent; FY2023-24]"
        "\u2192 Company: Example Industries Ltd"
    )
    assert "source: doc 3f2a1c000000…, p.46" in text
    assert 'quote: "Mr. Anil Kumar Sharma | Independent Director | 01234567"' in text
    assert "P:1" not in text and "C:1" not in text  # names, not ids
    assert items[0].kind == "triple" and items[0].ref_id == "e1"
    assert prov["e1"] == {
        "doc_id": DOC,
        "page_start": 46,
        "page_end": 46,
        "section": "DIRECTOR_OF",
        "fiscal_year": "FY2023-24",
    }


def test_transaction_is_one_item_with_both_parties_amount_and_relationship() -> None:
    group = [_txn_party("t-r", "C:1", "reporting"), _txn_party("t-c", "C:2", "counterparty")]
    items, prov = serialize(group, NAMES)
    assert len(items) == 1
    text = items[0].text
    assert (
        "Company: Example Industries Ltd \u2014"
        "[RELATED-PARTY TXN FY2022-23: Sale of goods; \u20b9 48.20 crore]"
        "\u2192 Company: Example Trading Pvt Ltd" in text
    )
    assert "(relationship: Entity controlled by promoter)" in text
    assert "p.212" in text
    assert items[0].ref_id == "t-r,t-c" and "t-r,t-c" in prov


def test_transaction_without_its_counterparty_says_so() -> None:
    items, _ = serialize([_txn_party("t-r", "C:1", "reporting")], NAMES)
    assert "(counterparty not retrieved)" in items[0].text


def test_every_item_states_a_source_or_that_none_was_recorded() -> None:
    sourced = triple(
        "AUDITED_BY", "C:1", "A:1", edge_id="a1", doc_id=DOC, page=87, quote="Deloitte"
    )
    unsourced = triple("HOLDS_STAKE", "C:1", "C:2", edge_id="h1", fy="", pledged_pct=12.5)
    items, prov = serialize([sourced, unsourced], NAMES)
    assert "source: doc" in items[0].text and "p.87" in items[0].text
    assert "source: not recorded" in items[1].text
    assert "12.5% pledged" in items[1].text
    assert prov["h1"]["doc_id"] == ""


def test_unknown_entities_fall_back_to_their_id() -> None:
    items, _ = serialize([triple(src="P:404", dst="C:1", edge_id="e")], NAMES)
    assert items[0].text.startswith("Person: P:404")


def test_format_crore() -> None:
    assert format_crore(482000000.0) == "₹ 48.20 crore"
    assert format_crore(12_345_678_900) == "₹ 1,234.57 crore"
    assert format_crore(None) == ""
    assert format_crore("n/a") == ""
