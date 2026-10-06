import re

MULTIPLIERS = {
    "crore": 1e7,
    "crores": 1e7,
    "cr": 1e7,
    "lakh": 1e5,
    "lakhs": 1e5,
    "lac": 1e5,
    "lacs": 1e5,
    "million": 1e6,
    "millions": 1e6,
    "mn": 1e6,
    "billion": 1e9,
    "billions": 1e9,
    "bn": 1e9,
    "thousand": 1e3,
    "thousands": 1e3,
    "'000": 1e3,
}

# Unit words must stand alone: a bare "cr"/"lac"/"mn" inside "credit",
# "place" or "column" is not a unit.
UNIT_RE = re.compile(
    r"(?<![a-z])(crores?|cr|lakhs?|lacs?|millions?|mn|billions?|bn|thousands?)(?![a-z])"
    r"|('000)(?!\d)",
    re.IGNORECASE,
)
NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def detect_unit(context_text: str) -> str | None:
    if not context_text:
        return None
    m = UNIT_RE.search(context_text.replace("\u2019", "'"))
    return (m.group(1) or m.group(2)).lower() if m else None


def to_rupees(value: float, unit: str | None) -> float | None:
    if unit is None or unit not in MULTIPLIERS:
        return None  # unknown unit → send to review; never guess
    return value * MULTIPLIERS[unit]


def parse_printed_number(text: str) -> float | None:
    """First number in `text` as printed (Indian or western digit grouping).
    The "'000" unit marker is not a number."""
    if not text:
        return None
    m = NUMBER_RE.search(text.replace("\u2019", "'").replace("'000", " "))
    return float(m.group().replace(",", "")) if m else None


def rupees_from_raw(amount_raw: str) -> float | None:
    """Rupee value of an amount copied as printed with its unit, e.g.
    "12.5 (₹ crore)" → 125000000.0. None when either part is missing."""
    value = parse_printed_number(amount_raw)
    if value is None:
        return None
    return to_rupees(value, detect_unit(amount_raw))
