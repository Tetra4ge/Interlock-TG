import pytest

from server.eval.normalize import entity_match, parse_number_crore, split_list


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("₹ 12.5 crore", 12.5),
        ("H4,807 crore", 4807.0),
        ("1,25,00,000", 1.25),
        ("50 lakh", 0.5),
        ("2310", 2310.0),
    ],
)
def test_parse_number_crore(text: str, expected: float) -> None:
    assert parse_number_crore(text) == pytest.approx(expected)


def test_parse_number_crore_without_digits_is_none() -> None:
    assert parse_number_crore("not found in the data") is None


def test_entity_match_ignores_punctuation_and_suffixes() -> None:
    assert entity_match("B S R & Co. LLP", "B S R and Co LLP")


def test_entity_match_fuzzy_for_close_names() -> None:
    assert entity_match("Deloitte Haskins and Sells LLP", "Deloitte Haskins & Sells")


def test_entity_match_rejects_different_companies() -> None:
    assert not entity_match("Bajaj Finserv", "Bajaj Finance")


def test_split_list_on_semicolons_and_newlines() -> None:
    assert split_list("A; B\nC") == ["A", "B", "C"]
    assert split_list(["A", " ", "B"]) == ["A", "B"]
