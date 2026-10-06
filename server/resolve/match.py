import hashlib
from typing import Any

from rapidfuzz import fuzz

from server.resolve.mentions import Mention
from server.resolve.normalize import initials_signature, surname_key


def person_score(a: str, b: str) -> float:
    base = fuzz.token_sort_ratio(a, b)
    # "a sharma" vs "r sharma" must never merge
    if initials_signature(a) != initials_signature(b) and not (
        set(initials_signature(a)) <= set(initials_signature(b))
        or set(initials_signature(b)) <= set(initials_signature(a))
    ):
        return 0.0
    return base


def company_score(a: str, b: str) -> float:
    # Not token_set_ratio: it scores 100 whenever one name's words are a
    # subset of the other's, which would merge "tata motors" with
    # "tata motors finance" -- a parent with its subsidiary.
    return fuzz.token_sort_ratio(a, b)


def get_block_key(mention: Mention) -> str:
    """Group candidates likely to match to avoid O(N^2) global comparisons."""
    if mention.kind == "person":
        sk = surname_key(mention.norm_name)
        ctx = mention.context_company_id or "unknown"
        return f"person:{sk}:{ctx}"
    elif mention.kind == "company":
        tokens = mention.norm_name.split()
        prefix = " ".join(tokens[:2]) if len(tokens) >= 2 else mention.norm_name
        return f"company:{prefix}"
    elif mention.kind == "audit_firm":
        tokens = mention.norm_name.split()
        prefix = tokens[0] if tokens else ""
        return f"audit_firm:{prefix}"
    return "unknown"


def generate_exact_id(mention: Mention) -> str | None:
    """Priority 1-3: Return exact official entity ID if present."""
    if mention.kind == "person" and "din" in mention.ids:
        return f"P:{mention.ids['din']}"
    if mention.kind == "company":
        if "company_id" in mention.ids:
            return f"C:{mention.ids['company_id']}"
        if "cin" in mention.ids:
            return f"C:{mention.ids['cin']}"
    if mention.kind == "audit_firm" and "frn" in mention.ids:
        return f"A:{mention.ids['frn']}"
    return None


def generate_fallback_id(mention: Mention) -> str:
    """Priority 7: Generate a stable hashed ID for a new entity."""
    h = hashlib.sha256(mention.norm_name.encode()).hexdigest()[:8]
    prefix = {"person": "P", "company": "C", "audit_firm": "A"}.get(mention.kind, "X")
    return f"{prefix}:x{h}"


def compare_mentions(
    m1: Mention, m2: Mention, auto_merge_threshold: float = 95.0, review_band_low: float = 80.0
) -> dict[str, Any] | None:
    """Evaluates Priorities 4, 5, and 6. Returns match result or None."""
    if m1.kind != m2.kind:
        return None

    # Special rule: never fuzzy-merge two mentions with DIFFERENT official IDs
    for k in m1.ids:
        if k in m2.ids and m1.ids[k] != m2.ids[k]:
            return None

    if m1.norm_name == m2.norm_name:
        return {"method": "exact_name", "score": 100.0}

    if m1.kind == "person":
        score = person_score(m1.norm_name, m2.norm_name)
    else:
        score = company_score(m1.norm_name, m2.norm_name)

    if score >= auto_merge_threshold:
        return {"method": "fuzzy", "score": score}

    if score >= review_band_low:
        return {"method": "review_queue", "score": score}

    return None
