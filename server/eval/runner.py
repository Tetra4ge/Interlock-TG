import json
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any, Protocol

import numpy as np

from server.common.git import git_state
from server.eval.models import Question
from server.eval.normalize import parse_number_crore, split_list
from server.eval.scorers import (
    citation_accuracy,
    score_abstention,
    score_entity,
    score_list,
    score_number,
    score_yes_no,
)
from server.eval.stats import bootstrap_ci
from server.pipelines.config import RETRIEVAL
from server.pipelines.models import AnswerResult, AnswerType, Status

QUESTIONS_PATH = Path("data/eval/questions_v1.jsonl")
RUNS_DIR = Path("data/eval/runs")


class Answerer(Protocol):
    def answer(self, question: str, request_id: str) -> AnswerResult: ...


def load_questions(path: Path = QUESTIONS_PATH) -> list[Question]:
    return [Question.model_validate_json(line) for line in path.read_text().splitlines() if line]


def _score_answer(q: Question, pred: str) -> float:
    gold = q.gold_answer
    if q.answer_type == AnswerType.ENTITY:
        return score_entity(pred, str(gold))
    if q.answer_type == AnswerType.YES_NO:
        return score_yes_no(pred, str(gold))
    if q.answer_type == AnswerType.NUMBER:
        return score_number(parse_number_crore(pred), float(str(gold)))
    if q.answer_type == AnswerType.LIST and isinstance(gold, (str, list)):
        return score_list(split_list(pred), split_list(gold))
    raise ValueError(f"Unsupported answer type for scoring: {q.answer_type} ({q.qid})")


def score_result(q: Question, r: AnswerResult) -> dict[str, Any]:
    abstained = r.status == Status.ABSTAINED
    errored = r.status == Status.ERROR
    if not q.answerable:
        correct = score_abstention(False, abstained)
    elif errored or abstained:
        correct = 0.0
    else:
        correct = _score_answer(q, r.answer_short)
    return {
        "qid": q.qid,
        "category": q.category,
        "correct": correct,
        "abstained": abstained,
        "error": errored,
        "citation_accuracy": citation_accuracy(
            [(c.doc_id, c.page) for c in r.citations],
            [(e.doc_id, e.page) for e in q.gold_evidence],
        ),
        "latency_ms": r.usage.latency_ms,
        "cost_usd": r.usage.cost_usd,
        "llm_calls": r.usage.llm_calls,
    }


def _aggregate(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    correct = [r["correct"] for r in rows]
    mean, lo, hi = bootstrap_ci(correct) if correct else (float("nan"), float("nan"), float("nan"))
    cit = [r["citation_accuracy"] for r in rows if r["citation_accuracy"] is not None]
    lat = [r["latency_ms"] for r in rows]
    return {
        "n": len(rows),
        "correct_mean": mean,
        "correct_ci95": [lo, hi],
        "citation_accuracy_mean": float(np.mean(cit)) if cit else None,
        "abstention_rate": sum(r["abstained"] for r in rows) / len(rows) if rows else None,
        "error_count": sum(r["error"] for r in rows),
        "latency_median_ms": median(lat) if lat else None,
        "latency_p90_ms": float(np.percentile(lat, 90)) if lat else None,
        "cost_usd_mean": float(np.mean([r["cost_usd"] for r in rows])) if rows else None,
        "llm_calls_mean": float(np.mean([r["llm_calls"] for r in rows])) if rows else None,
    }


def summarize(scores: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(scores)
    by_cat: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_cat[r["category"]].append(r)
    return {
        "overall": _aggregate(rows),
        "by_category": {cat: _aggregate(items) for cat, items in sorted(by_cat.items())},
    }


def _load_results(path: Path) -> dict[str, AnswerResult]:
    if not path.exists():
        return {}
    out: dict[str, AnswerResult] = {}
    for line in path.read_text().splitlines():
        if line:
            rec = json.loads(line)
            out[rec["qid"]] = AnswerResult.model_validate(rec["result"])
    return out


def run_eval(
    pipeline_name: str,
    split: str,
    *,
    run_id: str | None = None,
    limit: int | None = None,
    pipeline: Answerer | None = None,
    questions: Sequence[Question] | None = None,
    runs_dir: Path = RUNS_DIR,
) -> dict[str, Any]:
    if pipeline is None:
        import server.pipelines.rag  # noqa: F401  (registers "rag")
        from server.pipelines.base import REGISTRY

        pipeline = REGISTRY[pipeline_name]

    qs = list(questions) if questions is not None else load_questions()
    qs = [q for q in qs if q.split == split]
    if limit is not None:
        qs = qs[:limit]

    run_id = run_id or f"{pipeline_name}-{split}-{datetime.now(UTC):%Y%m%dT%H%M%S}"
    out = runs_dir / run_id
    out.mkdir(parents=True, exist_ok=True)
    config_path = out / "config.json"
    if not config_path.exists():
        config = {
            "run_id": run_id,
            "pipeline": pipeline_name,
            "split": split,
            "questions_version": qs[0].version if qs else None,
            "retrieval": RETRIEVAL.model_dump(),
            "started_at": datetime.now(UTC).isoformat(),
            **git_state(),
        }
        config_path.write_text(json.dumps(config, indent=2))

    results_path = out / "results.jsonl"
    done = set(_load_results(results_path))
    with results_path.open("a") as f:
        for q in qs:
            if q.qid in done:
                continue
            res = pipeline.answer(q.question, f"{run_id}:{q.qid}")
            f.write(json.dumps({"qid": q.qid, "result": res.model_dump(mode="json")}) + "\n")
            f.flush()

    records = _load_results(results_path)
    scores = [score_result(q, records[q.qid]) for q in qs if q.qid in records]
    (out / "scores.jsonl").write_text("".join(json.dumps(s) + "\n" for s in scores))
    summary = summarize(scores)
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    return summary
