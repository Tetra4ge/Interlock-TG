import re

from rapidfuzz import fuzz

ENTITY_FUZZY_THRESHOLD = 92

_SUFFIXES = re.compile(r"\b(llp|ltd|limited|pvt|private|co|company|the)\b")
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_CRORE_FACTORS = {"crore": 1.0, "lakh": 0.01, "million": 0.1, "billion": 100.0}


def norm_text(s: str) -> str:
    s = s.lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = _SUFFIXES.sub(" ", s)
    return " ".join(s.split())


def entity_match(a: str, b: str) -> bool:
    na, nb = norm_text(a), norm_text(b)
    if not na or not nb:
        return False
    return na == nb or fuzz.token_sort_ratio(na, nb) >= ENTITY_FUZZY_THRESHOLD


def split_list(s: str | list[str]) -> list[str]:
    if isinstance(s, list):
        return [x for x in s if x.strip()]
    return [x.strip() for x in re.split(r";|\n", s) if x.strip()]


def parse_number_crore(s: str) -> float | None:
    """Parse the first number in `s` and express it in crore.

    A number with no unit and at least a million is treated as rupees, so
    "1,25,00,000" becomes 1.25 crore. Units other than crore are converted.
    """
    m = _NUMBER.search(s)
    if not m:
        return None
    value = float(m.group().replace(",", ""))
    lowered = s.lower()
    for unit, factor in _CRORE_FACTORS.items():
        if unit in lowered:
            return value * factor
    if value >= 1_000_000:
        return value / 10_000_000
    return value
