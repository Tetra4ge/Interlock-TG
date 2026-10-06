from types import SimpleNamespace

from server.extract.grounding import check_grounding


def _rec(quote: str, **fields: object) -> SimpleNamespace:
    return SimpleNamespace(evidence=SimpleNamespace(quote=quote, page=1), **fields)


def _parsed(text: str) -> dict:
    return {"pages": [{"page_no": 1, "cleaned_text": text}]}


def test_missing_optional_percentage_is_not_checked() -> None:
    text = "Tata Steel Downstream Products Limited is a wholly owned subsidiary"
    rec = _rec(text, subsidiary_name="Tata Steel Downstream Products Limited", pct_held=None)
    assert check_grounding(rec, _parsed(text)) == ("accepted", "")


def test_whole_number_percentage_matches_as_printed() -> None:
    text = "Bajaj Holdings and Investment Limited | 10 | Nil"
    rec = _rec(text, holder_name="Bajaj Holdings", holder_kind="company", pct_holding=10.0)
    assert check_grounding(rec, _parsed(text)) == ("accepted", "")


def test_amount_is_matched_on_its_figure_not_its_unit_text() -> None:
    text = "Tata Sons Private Limited | Dividend paid | 1,250.75"
    rec = _rec(text, amount_inr=0.0, amount_raw="1,250.75 (₹ crore)")
    assert check_grounding(rec, _parsed(text)) == ("accepted", "")


def test_invented_percentage_is_rejected() -> None:
    text = "Bajaj Holdings and Investment Limited | 10 | Nil"
    rec = _rec(text, holder_name="Bajaj Holdings", holder_kind="company", pct_holding=35.5)
    assert check_grounding(rec, _parsed(text)) == ("rejected", "ungrounded_number")
