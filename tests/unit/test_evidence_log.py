import pytest

from server.parse.tokens import estimate_tokens
from server.pipelines.agent.evidence_log import EvidenceLog, recent_labels
from server.pipelines.agent.state import AgentState, Budget, Step
from server.pipelines.common.budget import LABEL_OVERHEAD_TOKENS


def test_labels_are_sequential_and_start_at_e1() -> None:
    log = EvidenceLog()
    assert log.add("triple", "e-a", "fact a", "doc", 5) == "E1"
    assert log.add("chunk", "c-b", "fact b", "doc", 6, 7) == "E2"
    assert log.provenance["c-b"]["page_end"] == 7
    assert log.provenance["e-a"]["page_end"] == 5  # a single page by default


def test_the_same_ref_id_keeps_its_label() -> None:
    log = EvidenceLog()
    first = log.add("triple", "e-a", "fact a")
    log.add("triple", "e-b", "fact b")
    assert log.add("triple", "e-a", "fact a again") == first
    assert len(log) == 2
    assert log.items[0].text == "fact a"


def test_lookup_by_label() -> None:
    log = EvidenceLog()
    log.add("triple", "e-a", "fact a")
    assert log.item_for_label("E1").text == "fact a"  # type: ignore[union-attr]
    for bad in ("E2", "E0", "x", "E1; DROP", ""):
        assert log.item_for_label(bad) is None


def _log(n: int, words: int = 5) -> EvidenceLog:
    log = EvidenceLog()
    for i in range(n):
        log.add("chunk", f"r{i}", "word " * words, "d", i)
    return log


def test_everything_fits_when_the_budget_is_large() -> None:
    items, prov = _log(5).prioritized(10_000, "", [])
    assert [i.ref_id for i in items] == [f"r{i}" for i in range(5)]
    assert set(prov) == {i.ref_id for i in items}


def test_cited_then_recent_then_rest_when_the_budget_is_tight() -> None:
    log = _log(6, words=100)
    per_item = estimate_tokens("word " * 100) + LABEL_OVERHEAD_TOKENS
    items, _ = log.prioritized(per_item * 3, "I relied on [E6] and E2.", ["E4"])
    refs = [i.ref_id for i in items]
    # cited E2 and E6 first (log order), then the item from the latest step (E4)
    assert refs == ["r1", "r5", "r3"]  # the recent step's item fills the last slot


def test_budget_is_never_exceeded() -> None:
    log = _log(20, words=80)
    budget = 400
    items, _ = log.prioritized(budget, "", [])
    assert sum(estimate_tokens(i.text) + LABEL_OVERHEAD_TOKENS for i in items) <= budget


def test_recent_labels_come_from_the_last_three_steps() -> None:
    steps = [Step(n=i, tool="t", args={}, ok=True, result_labels=[f"E{i}"]) for i in range(1, 6)]
    assert recent_labels(steps) == ["E3", "E4", "E5"]
    assert recent_labels([]) == []


def test_budget_checks_report_which_limit_was_hit() -> None:
    budget = Budget(max_steps=2, max_tokens=100, timeout_s=60)
    st = AgentState(question="q")
    assert st.check_budget(budget) is None
    st.tokens_used = 100
    assert st.check_budget(budget) == "max_tokens"
    st.tokens_used = 0
    st.steps = [Step(n=i, tool="t", args={}, ok=True) for i in (1, 2)]
    assert st.check_budget(budget) == "max_steps"
    st.steps = []
    st.started -= 61
    assert st.check_budget(budget) == "timeout"


def test_each_half_of_a_transaction_id_finds_the_same_label() -> None:
    log = EvidenceLog()
    label = log.add("triple", "t1-r,t1-c", "txn text")
    assert log.label_of("t1-r") == label == log.label_of("t1-c") == log.label_of("t1-r,t1-c")
    assert log.add("triple", "t1-c", "again") == label  # no duplicate entry
    assert len(log) == 1


def _relevance(scores: dict[str, float]):  # type: ignore[no-untyped-def]
    return lambda texts: [scores[t] for t in texts]


def test_relevance_beats_recency_when_the_log_does_not_fit() -> None:
    log = EvidenceLog()
    log.add("chunk", "auditor", "auditor " + "pad " * 150)  # E1: the answer, found early
    for i in range(4):
        log.add("chunk", f"noise{i}", f"noise{i} " + "pad " * 150)  # E2..E5: later, irrelevant
    scores = {"auditor " + "pad " * 150: 0.9}
    scores.update({f"noise{i} " + "pad " * 150: 0.1 for i in range(4)})
    per_item = estimate_tokens("auditor " + "pad " * 150) + LABEL_OVERHEAD_TOKENS

    items, _ = log.prioritized(per_item * 2, "", ["E2", "E3", "E4", "E5"], _relevance(scores))

    assert items[0].ref_id == "auditor"  # it would have been dropped by recency alone


def test_without_a_scorer_recent_steps_still_come_first() -> None:
    log = _log(5, words=100)
    per_item = estimate_tokens("word " * 100) + LABEL_OVERHEAD_TOKENS
    items, _ = log.prioritized(per_item * 2, "", ["E4", "E5"])
    assert [i.ref_id for i in items] == ["r3", "r4"]


def test_cited_items_stay_first_even_against_more_relevant_ones() -> None:
    log = _log(4, words=100)
    texts = [i.text for i in log.items]
    scores = dict.fromkeys(texts, 0.9)
    per_item = estimate_tokens(texts[0]) + LABEL_OVERHEAD_TOKENS
    items, _ = log.prioritized(per_item, "I used E3", [], _relevance(scores))
    assert [i.ref_id for i in items] == ["r2"]


def test_a_failing_scorer_falls_back_to_recency() -> None:
    log = _log(5, words=100)
    per_item = estimate_tokens("word " * 100) + LABEL_OVERHEAD_TOKENS

    def boom(texts: list[str]) -> list[float]:
        raise RuntimeError("embedding model unavailable")

    items, _ = log.prioritized(per_item * 2, "", ["E4", "E5"], boom)
    assert [i.ref_id for i in items] == ["r3", "r4"]


def test_the_scorer_is_not_called_when_everything_fits() -> None:
    calls: list[int] = []

    def spy(texts: list[str]) -> list[float]:
        calls.append(1)
        return [0.0] * len(texts)

    items, _ = _log(3).prioritized(10_000, "", [], spy)
    assert calls == [] and len(items) == 3


def test_question_similarity_is_cosine_of_normalised_embeddings(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from server.embed import provider, query
    from server.pipelines.agent.evidence_log import question_similarity

    monkeypatch.setattr(query, "embed_query", lambda q: [1.0, 0.0])
    monkeypatch.setattr(
        provider, "embed_texts", lambda texts, is_query=False: [[1.0, 0.0], [0.0, 1.0], [0.6, 0.8]]
    )
    assert question_similarity("q", ["a", "b", "c"]) == pytest.approx([1.0, 0.0, 0.6])
    assert question_similarity("q", []) == []
