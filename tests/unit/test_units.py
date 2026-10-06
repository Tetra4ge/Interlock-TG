import pytest

from server.extract.units import detect_unit, parse_printed_number, rupees_from_raw


@pytest.mark.parametrize(
    ("text", "unit"),
    [
        ("₹ in crore", "crore"),
        ("12.5 (₹ crore)", "crore"),
        ("Rs. in lakhs", "lakhs"),
        ("Amount in Mn", "mn"),
        ("450 Cr.", "cr"),
        ("1,234 (₹ '000)", "'000"),
        ("USD 3 billion", "billion"),
    ],
)
def test_detects_standalone_unit_words(text: str, unit: str) -> None:
    assert detect_unit(text) == unit


@pytest.mark.parametrize(
    "text", ["Amount credited", "increase of 500", "replaced 40 units", "column 3", "12.5", ""]
)
def test_unit_letters_inside_other_words_are_not_units(text: str) -> None:
    assert detect_unit(text) is None


def test_parses_number_as_printed() -> None:
    assert parse_printed_number("1,25,000.50 (₹ lakh)") == 125000.50
    assert parse_printed_number("₹ '000: 1,234") == 1234
    assert parse_printed_number("nil") is None


def test_rupees_from_raw() -> None:
    assert rupees_from_raw("12.5 (₹ crore)") == 125_000_000.0
    assert rupees_from_raw("2 lakhs") == 200_000.0
    assert rupees_from_raw("12.5") is None  # unit unknown: never guess
    assert rupees_from_raw("crore") is None
