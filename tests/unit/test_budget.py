from server.parse.tokens import estimate_tokens
from server.pipelines.common.budget import LABEL_OVERHEAD_TOKENS, fit_to_budget
from server.pipelines.models import EvidenceItem


def _item(ref_id: str, text: str) -> EvidenceItem:
    return EvidenceItem(kind="chunk", ref_id=ref_id, text=text)


def test_never_exceeds_budget() -> None:
    items = [_item(f"c{i}", "word " * 200) for i in range(10)]
    budget = 300
    kept = fit_to_budget(items, budget)

    used = sum(estimate_tokens(i.text) + LABEL_OVERHEAD_TOKENS for i in kept)
    assert used <= budget


def test_keeps_priority_order() -> None:
    items = [_item("best", "short"), _item("worst", "short")]
    kept = fit_to_budget(items, budget_tokens=10_000)

    assert [i.ref_id for i in kept] == ["best", "worst"]


def test_skips_oversized_item_but_keeps_smaller_later_ones() -> None:
    huge = _item("huge", "word " * 10_000)  # far exceeds the budget alone
    small = _item("small", "short text")
    kept = fit_to_budget([huge, small], budget_tokens=100)

    assert [i.ref_id for i in kept] == ["small"]


def test_empty_input() -> None:
    assert fit_to_budget([], budget_tokens=1000) == []
