from server.parse.tokens import estimate_tokens
from server.pipelines.models import EvidenceItem

LABEL_OVERHEAD_TOKENS = 30  # rough allowance for the "[E1] (...)" header


def fit_to_budget(items: list[EvidenceItem], budget_tokens: int) -> list[EvidenceItem]:
    """Items must already be sorted by priority (best first). Skips
    oversized items rather than truncating them, so later, smaller items
    still get a chance to fit."""
    kept: list[EvidenceItem] = []
    used = 0
    for item in items:
        t = estimate_tokens(item.text) + LABEL_OVERHEAD_TOKENS
        if used + t > budget_tokens:
            continue
        kept.append(item)
        used += t
    return kept
