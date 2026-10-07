from pydantic import BaseModel

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


class BudgetSplit(BaseModel):
    total: int
    primary_tokens: int
    secondary_tokens: int


def item_tokens(item: EvidenceItem) -> int:
    return estimate_tokens(item.text) + LABEL_OVERHEAD_TOKENS


def split_budget(
    primary: list[EvidenceItem],
    secondary: list[EvidenceItem],
    total_tokens: int,
    primary_share: float,
) -> tuple[list[EvidenceItem], BudgetSplit]:
    """Primary items first, up to `primary_share` of the budget; secondary items
    fill whatever is left (including primary's unused share). The combined list
    never exceeds `total_tokens`."""
    kept_primary = fit_to_budget(primary, int(total_tokens * primary_share))
    primary_used = sum(item_tokens(i) for i in kept_primary)
    kept_secondary = fit_to_budget(secondary, total_tokens - primary_used)
    secondary_used = sum(item_tokens(i) for i in kept_secondary)
    return kept_primary + kept_secondary, BudgetSplit(
        total=total_tokens, primary_tokens=primary_used, secondary_tokens=secondary_used
    )
