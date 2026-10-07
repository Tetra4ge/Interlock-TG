import json
from pathlib import Path

import pytest

from server.eval.compare import MIN_PAIRS, compare_runs, load_scores


def _rows(values: dict[str, float | None], category: str = "multi_hop", metric: str = "correct"):  # type: ignore[no-untyped-def]
    return [{"qid": q, "category": category, metric: v} for q, v in values.items()]


def test_a_consistent_advantage_has_a_positive_interval() -> None:
    qids = [f"q{i}" for i in range(20)]
    a = _rows({q: 1.0 for q in qids})
    b = _rows({q: 1.0 if i < 5 else 0.0 for i, q in enumerate(qids)})
    out = compare_runs(a, b)["overall"]
    assert out["n"] == 20
    assert out["diff"] == pytest.approx(0.75)
    assert out["ci95"][0] > 0
    assert out["verdict"] == "A better"


def test_swapping_the_runs_flips_the_verdict() -> None:
    qids = [f"q{i}" for i in range(20)]
    a = _rows({q: 1.0 for q in qids})
    b = _rows({q: 0.0 for q in qids})
    assert compare_runs(b, a)["overall"]["verdict"] == "B better"


def test_identical_runs_show_no_clear_difference() -> None:
    rows = _rows({f"q{i}": float(i % 2) for i in range(10)})
    out = compare_runs(rows, rows)["overall"]
    assert out["diff"] == 0 and out["verdict"] == "no clear difference"


def test_tiny_samples_do_not_get_a_confident_interval() -> None:
    a = _rows({f"q{i}": 1.0 for i in range(MIN_PAIRS - 1)})
    b = _rows({f"q{i}": 0.0 for i in range(MIN_PAIRS - 1)})
    out = compare_runs(a, b)["overall"]
    assert out["ci95"] is None and out["verdict"].startswith("too few pairs")
    assert out["diff"] == 1.0  # the observed difference is still reported


def test_only_questions_both_runs_scored_are_paired() -> None:
    a = _rows({"q1": 1.0, "q2": 1.0, "only-a": 0.0})
    b = _rows({"q1": 0.0, "q2": 0.0, "only-b": 1.0})
    assert compare_runs(a, b)["overall"]["n"] == 2


def test_no_overlap() -> None:
    out = compare_runs(_rows({"q1": 1.0}), _rows({"q2": 1.0}))["overall"]
    assert out == {"n": 0, "diff": None, "ci95": None, "verdict": "no paired questions"}


def test_missing_metric_values_are_left_out() -> None:
    a = _rows({"q1": 1.0, "q2": None}, metric="faithfulness")
    b = _rows({"q1": 0.0, "q2": 1.0}, metric="faithfulness")
    assert compare_runs(a, b, "faithfulness")["overall"]["n"] == 1


def test_categories_are_reported_separately() -> None:
    a = _rows({f"s{i}": 1.0 for i in range(6)}, "single_fact") + _rows(
        {f"m{i}": 1.0 for i in range(6)}, "multi_hop"
    )
    b = _rows({f"s{i}": 1.0 for i in range(6)}, "single_fact") + _rows(
        {f"m{i}": 0.0 for i in range(6)}, "multi_hop"
    )
    res = compare_runs(a, b)
    assert res["by_category"]["single_fact"]["diff"] == 0
    assert res["by_category"]["multi_hop"]["diff"] == 1.0


def test_unknown_metric_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown metric"):
        compare_runs([], [], "vibes")


def test_load_scores_reads_the_run_file_and_reports_a_missing_run(tmp_path: Path) -> None:
    run = tmp_path / "r1"
    run.mkdir()
    (run / "scores.jsonl").write_text(
        json.dumps({"qid": "q1", "category": "c", "correct": 1.0}) + "\n"
    )
    assert load_scores("r1", tmp_path)[0]["qid"] == "q1"
    with pytest.raises(FileNotFoundError, match="r2"):
        load_scores("r2", tmp_path)
