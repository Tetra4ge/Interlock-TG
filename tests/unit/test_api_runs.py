import math

import pytest

from server.api import runs as runs_mod
from server.api.runs import (
    _clean,
    compare_view,
    get_result,
    list_questions,
    list_runs,
    run_metrics,
)
from server.pipelines.models import Status
from tests.conftest import MemoryDB
from tests.unit.api_fixtures import answer_result, seed_question, seed_run


def _row(correct: float, label: str | None = None, status: Status = Status.OK, **kw):  # type: ignore[no-untyped-def]
    res_kw = {k: kw.pop(k) for k in ("cost", "latency_ms", "llm_calls", "tool_calls") if k in kw}
    return {
        "result": answer_result(status=status, **res_kw), "correct": correct,
        "failure_label": label, **kw,
    }  # fmt: skip


@pytest.fixture
def db(memdb: MemoryDB) -> MemoryDB:
    for qid, cat in [
        ("q1", "single_fact"),
        ("q2", "single_fact"),
        ("q3", "numerical"),
        ("q4", "unanswerable"),
    ]:
        seed_question(memdb, qid, cat)
    scored = {"faithfulness": 1.0, "citation_accuracy": 0.5, "evidence_recall": 1.0}
    missed = {"faithfulness": 0.0, "citation_accuracy": 0.0, "evidence_recall": 0.0}
    seed_run(memdb, "run-rag", "rag", rows={
        "q1": _row(1.0, **scored, cost=0.01, latency_ms=100),
        "q2": _row(0.0, "retrieval_miss", **missed, cost=0.03, latency_ms=300),
        "q3": _row(1.0, cost=0.02, latency_ms=200),
        "q4": _row(1.0, status=Status.ABSTAINED, cost=0.0, latency_ms=50),
    })  # fmt: skip
    return memdb


def test_runs_are_listed_newest_first_with_result_counts(db: MemoryDB) -> None:
    seed_run(db, "run-old", "rag")
    db.execute("UPDATE runs SET finished_at = '2025-01-01' WHERE run_id = 'run-old'")
    runs = list_runs(db)
    assert [r.run_id for r in runs] == ["run-rag", "run-old"]
    assert runs[0].n_results == 4 and runs[1].n_results == 0
    assert runs[0].git_commit == "abc123" and runs[0].pipeline == "rag"


def test_metrics_match_a_direct_computation_from_the_scores(db: MemoryDB) -> None:
    m = run_metrics(db, "run-rag")
    assert m is not None
    rows = db.execute(
        "SELECT correct, faithfulness, citation_accuracy, evidence_recall FROM scores"
    ).fetchall()

    def mean(i: int) -> float:
        vals = [r[i] for r in rows if r[i] is not None]
        return sum(vals) / len(vals)

    o = m.overall
    assert o.n == 4
    assert o.correct_mean == pytest.approx(mean(0)) == pytest.approx(0.75)
    assert o.faithfulness_mean == pytest.approx(mean(1)) == pytest.approx(0.5)
    assert o.citation_accuracy_mean == pytest.approx(mean(2)) == pytest.approx(0.25)
    assert o.evidence_recall_mean == pytest.approx(mean(3)) == pytest.approx(0.5)
    assert o.abstention_rate == 0.25
    assert o.cost_usd_mean == pytest.approx((0.01 + 0.03 + 0.02 + 0.0) / 4)
    assert o.latency_median_ms == pytest.approx(150) and o.latency_p90_ms is not None
    assert o.failures == {"retrieval_miss": 1}
    assert o.correct_ci95 is not None and o.correct_ci95[0] <= 0.75 <= o.correct_ci95[1]


def test_metrics_are_split_by_category(db: MemoryDB) -> None:
    m = run_metrics(db, "run-rag")
    assert m is not None
    assert set(m.by_category) == {"single_fact", "numerical", "unanswerable"}
    assert m.by_category["single_fact"].n == 2
    assert m.by_category["single_fact"].correct_mean == 0.5
    assert m.by_category["unanswerable"].abstention_rate == 1.0


def test_metrics_for_a_missing_or_empty_run_are_none(db: MemoryDB) -> None:
    assert run_metrics(db, "nope") is None
    seed_run(db, "empty", "rag")
    assert run_metrics(db, "empty") is None


def test_metrics_serialise_to_valid_json_even_with_one_row(db: MemoryDB) -> None:
    seed_run(db, "one", "agent", rows={"q1": _row(1.0, tool_calls=3, llm_calls=5)})
    m = run_metrics(db, "one")
    assert m is not None and m.overall.tool_calls_mean == 3
    assert "NaN" not in m.model_dump_json()


def test_clean_replaces_nan_and_infinity() -> None:
    assert _clean(float("nan")) is None and _clean(math.inf) is None
    assert _clean([1.0, float("nan")]) == [1.0, None] and _clean(0.5) == 0.5


def test_a_result_comes_with_its_score_and_question(db: MemoryDB) -> None:
    out = get_result(db, "run-rag", "q2")
    assert out is not None
    assert out.question == "question q2" and out.category == "single_fact"
    assert out.score is not None and out.score.failure_label == "retrieval_miss"
    assert out.result.pipeline == "rag"


def test_a_result_without_a_score_has_none(db: MemoryDB) -> None:
    db.execute(
        "INSERT INTO results (run_id, qid, answer_json) VALUES ('run-rag', 'qx', ?)",
        [answer_result().model_dump_json()],
    )
    out = get_result(db, "run-rag", "qx")
    assert out is not None and out.score is None and out.question is None


def test_unknown_results_are_none(db: MemoryDB) -> None:
    assert get_result(db, "run-rag", "zzz") is None and get_result(db, "zzz", "q1") is None


def test_gold_is_served_for_dev_and_hidden_for_test_unless_asked(db: MemoryDB) -> None:
    seed_question(
        db,
        "t1",
        "single_fact",
        split="test",
        gold="secret",
        gold_evidence=[{"doc_id": "d", "page": 1}],
    )
    seed_question(db, "d1", "single_fact", split="dev", gold="open")
    by_id = {q.qid: q for q in list_questions(db)}
    assert by_id["d1"].gold_answer == "open"
    assert by_id["t1"].gold_answer is None and by_id["t1"].gold_evidence is None
    shown = {q.qid: q for q in list_questions(db, include_gold=True)}
    assert shown["t1"].gold_answer == "secret" and shown["t1"].gold_evidence == [
        {"doc_id": "d", "page": 1}
    ]


def test_questions_can_be_filtered_by_split(db: MemoryDB) -> None:
    seed_question(db, "t1", split="test")
    assert {q.qid for q in list_questions(db, split="test")} == {"t1"}
    assert "t1" not in {q.qid for q in list_questions(db, split="dev")}


# --- the three-pipeline comparison ---------------------------------------------


def _three_runs(db: MemoryDB, n: int = 8, rag=None, graphrag=None, agent=None) -> None:  # type: ignore[no-untyped-def]
    """Each pipeline is a function question-index -> correct (0..1)."""
    rag = rag or (lambda i: 0.0 if i % 2 else 1.0)
    graphrag = graphrag or (lambda i: 1.0)
    agent = agent or (lambda i: 1.0)
    for i in range(n):
        seed_question(db, f"c{i}", "multi_hop" if i % 2 else "single_fact")
    for run_id, pipeline, fn in (
        ("r-rag", "rag", rag),
        ("r-gr", "graphrag", graphrag),
        ("r-ag", "agent", agent),
    ):
        seed_run(db, run_id, pipeline, rows={
            f"c{i}": _row(
                fn(i), "retrieval_miss" if fn(i) == 0 else None,
                tool_calls=3 if pipeline == "agent" else 0,
            )
            for i in range(n)
        })  # fmt: skip


def test_compare_joins_the_three_runs_per_question(db: MemoryDB) -> None:
    _three_runs(db)
    out = compare_view(db, {"rag": "r-rag", "graphrag": "r-gr", "agent": "r-ag"})
    assert [q.qid for q in out.questions] == sorted(f"c{i}" for i in range(8))
    first = next(q for q in out.questions if q.qid == "c1")
    assert set(first.cells) == {"rag", "graphrag", "agent"}
    assert (
        first.cells["rag"].correct == 0.0 and first.cells["rag"].failure_label == "retrieval_miss"
    )
    assert first.cells["agent"].tool_calls == 3 and first.question == "question c1"
    assert set(out.metrics) == {"rag", "graphrag", "agent"}


def test_paired_differences_are_reported_per_pair_and_category(db: MemoryDB) -> None:
    _three_runs(db)
    out = compare_view(db, {"rag": "r-rag", "graphrag": "r-gr", "agent": "r-ag"})
    assert [(p.a, p.b) for p in out.pairs] == [
        ("graphrag", "rag"),
        ("agent", "rag"),
        ("agent", "graphrag"),
    ]
    gr_rag = out.pairs[0]
    assert gr_rag.overall.n == 8 and gr_rag.overall.diff == pytest.approx(0.5)
    assert gr_rag.overall.verdict == "A better"
    assert gr_rag.by_category["multi_hop"].diff == pytest.approx(1.0)
    assert out.pairs[2].overall.verdict == "no clear difference"  # agent == graphrag


def test_a_tie_for_first_names_the_tied_pipelines(db: MemoryDB) -> None:
    _three_runs(db)
    out = compare_view(db, {"rag": "r-rag", "graphrag": "r-gr", "agent": "r-ag"})
    multi = out.leaders["multi_hop"]
    assert multi.pipeline is None and multi.tied == ["graphrag", "agent"] and multi.mean == 1.0
    assert "tie on mean accuracy: graphrag, agent" in multi.reason


def test_a_clear_lead_is_flagged_when_the_paired_difference_excludes_zero(db: MemoryDB) -> None:
    _three_runs(db, n=12, graphrag=lambda i: 0.5, agent=lambda i: 1.0)
    out = compare_view(db, {"rag": "r-rag", "graphrag": "r-gr", "agent": "r-ag"})
    multi = out.leaders["multi_hop"]
    assert (multi.pipeline, multi.runner_up, multi.clear) == ("agent", "graphrag", True)
    assert multi.reason == "paired difference excludes 0"


def test_a_lead_whose_interval_includes_zero_is_unclear(db: MemoryDB) -> None:
    graphrag = [1, 0, 1, 0, 1, 0, 1, 0]  # mean 0.50
    agent = [1, 1, 0, 0, 1, 1, 1, 0]  # mean 0.625, but only by chance-sized margins
    _three_runs(db, graphrag=lambda i: float(graphrag[i]), agent=lambda i: float(agent[i]))
    out = compare_view(db, {"graphrag": "r-gr", "agent": "r-ag"})
    overall = out.leaders["overall"]
    assert overall.pipeline == "agent" and overall.clear is False
    assert overall.reason.startswith("unclear: no clear difference")


def test_a_lead_over_too_few_questions_is_unclear(db: MemoryDB) -> None:
    for i in range(3):
        seed_question(db, f"s{i}")
    seed_run(db, "a", "agent", rows={f"s{i}": _row(1.0) for i in range(3)})
    seed_run(db, "b", "rag", rows={f"s{i}": _row(0.0) for i in range(3)})
    out = compare_view(db, {"agent": "a", "rag": "b"})
    leader = out.leaders["single_fact"]
    assert leader.pipeline == "agent" and leader.clear is False and "too few pairs" in leader.reason


def test_a_single_run_has_a_leader_but_no_comparison(db: MemoryDB) -> None:
    out = compare_view(db, {"rag": "run-rag"})
    assert out.leaders["overall"].pipeline == "rag" and out.leaders["overall"].clear is False
    assert out.pairs == []


def test_unknown_runs_are_skipped(db: MemoryDB) -> None:
    out = compare_view(db, {"rag": "run-rag", "agent": "missing"})
    assert set(out.metrics) == {"rag"}


def test_compare_with_no_runs_is_empty(db: MemoryDB) -> None:
    out = compare_view(db, {})
    assert out.questions == [] and out.leaders["overall"].pipeline is None
    assert runs_mod.PAIRS
