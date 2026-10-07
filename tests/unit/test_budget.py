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


def _triple(ref_id: str, words: int) -> EvidenceItem:
    return EvidenceItem(kind="triple", ref_id=ref_id, text="word " * words)


def test_split_total_never_exceeds_budget() -> None:
    from server.pipelines.common.budget import item_tokens, split_budget

    triples = [_triple(f"t{i}", 60) for i in range(30)]
    chunks = [_item(f"c{i}", "word " * 150) for i in range(10)]
    items, split = split_budget(triples, chunks, 1000, 0.6)

    assert sum(item_tokens(i) for i in items) <= 1000
    assert split.primary_tokens <= 600
    assert split.primary_tokens + split.secondary_tokens <= 1000


def test_split_gives_unused_triple_budget_to_chunks() -> None:
    from server.pipelines.common.budget import split_budget

    chunks = [_item(f"c{i}", "word " * 100) for i in range(10)]
    full = [_triple(f"t{i}", 60) for i in range(30)]  # more than the 60% share can hold
    with_triples, split_full = split_budget(full, chunks, 1000, 0.6)
    without, split_none = split_budget([], chunks, 1000, 0.6)

    def n_chunks(items: list[EvidenceItem]) -> int:
        return sum(i.kind == "chunk" for i in items)

    assert split_none.primary_tokens == 0
    assert n_chunks(without) > n_chunks(with_triples)
    assert split_full.primary_tokens + split_full.secondary_tokens <= 1000


def test_split_puts_triples_before_chunks() -> None:
    from server.pipelines.common.budget import split_budget

    items, _ = split_budget([_triple("t", 5)], [_item("c", "text")], 1000, 0.6)
    assert [i.kind for i in items] == ["triple", "chunk"]
