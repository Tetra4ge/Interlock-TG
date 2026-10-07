import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from server.eval.runner import RUNS_DIR
from server.eval.stats import paired_diff_ci

METRICS = ("correct", "citation_accuracy", "evidence_recall", "faithfulness")
# With fewer pairs a bootstrap interval collapses to the observed difference and
# looks far more certain than it is.
MIN_PAIRS = 5


def load_scores(run_id: str, runs_dir: Path = RUNS_DIR) -> list[dict[str, Any]]:
    path = runs_dir / run_id / "scores.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"No scores for run {run_id!r} (looked in {path})")
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def _entry(a: dict[str, float], b: dict[str, float]) -> dict[str, Any]:
    n = len(set(a) & set(b))
    if n == 0:
        return {"n": 0, "diff": None, "ci95": None, "verdict": "no paired questions"}
    diff, lo, hi = paired_diff_ci(a, b)
    if n < MIN_PAIRS:
        return {"n": n, "diff": diff, "ci95": None, "verdict": f"too few pairs (<{MIN_PAIRS})"}
    verdict = "A better" if lo > 0 else "B better" if hi < 0 else "no clear difference"
    return {"n": n, "diff": diff, "ci95": [lo, hi], "verdict": verdict}


def compare_runs(
    rows_a: list[dict[str, Any]], rows_b: list[dict[str, Any]], metric: str = "correct"
) -> dict[str, Any]:
    """Paired bootstrap of (A - B) on the questions both runs scored, overall and
    per category. Positive means A is better. Questions where either run has no
    value for the metric (e.g. no judge verdict) are left out of that metric."""
    if metric not in METRICS:
        raise ValueError(f"Unknown metric {metric!r}. Choose from {METRICS}")

    def values(rows: list[dict[str, Any]]) -> dict[str, float]:
        return {r["qid"]: float(r[metric]) for r in rows if r.get(metric) is not None}

    cat_of = {r["qid"]: r["category"] for r in rows_a}
    va, vb = values(rows_a), values(rows_b)
    shared = set(va) & set(vb)

    by_cat: dict[str, set[str]] = defaultdict(set)
    for qid in shared:
        by_cat[cat_of.get(qid, "unknown")].add(qid)

    return {
        "metric": metric,
        "overall": _entry({q: va[q] for q in shared}, {q: vb[q] for q in shared}),
        "by_category": {
            cat: _entry({q: va[q] for q in qids}, {q: vb[q] for q in qids})
            for cat, qids in sorted(by_cat.items())
        },
    }
