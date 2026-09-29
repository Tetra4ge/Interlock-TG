import re

MULTIPLIERS = {
    "crore": 1e7, "crores": 1e7, "cr": 1e7,
    "lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "lacs": 1e5,
    "million": 1e6, "mn": 1e6, "thousand": 1e3, "'000": 1e3
}

UNIT_RE = re.compile(
    r"(?:₹|rs\.?|inr)?\s*(?:in\s+)?(crores?|cr|lakhs?|lacs?|million|mn|thousand|'000)",
    re.IGNORECASE
)

def detect_unit(context_text: str) -> str | None:
    if not context_text:
        return None
    m = UNIT_RE.search(context_text)
    return m.group(1).lower() if m else None

def to_rupees(value: float, unit: str | None) -> float | None:
    if unit is None or unit not in MULTIPLIERS:
        return None          # unknown unit → send to review; never guess
    return value * MULTIPLIERS[unit]
