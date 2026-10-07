"""Read-only views over the run store (runs / results / scores / questions).

No business logic of its own: metrics come from the eval harness's `summarize`,
paired differences from `compare_runs`, so the dashboard cannot disagree with
`hl eval` and `hl compare`."""

import json
import math
from typing import Any

from server.api.schemas import (
    CompareRunsOut,
    Leader,
    MetricsBlock,
    PairEntry,
    PairResult,
    PipelineCell,
    QuestionOut,
    QuestionRow,
    ResultOut,
    RunMetrics,
    RunOut,
    ScoreRow,
)
from server.eval.compare import compare_runs
from server.eval.runner import summarize
from server.pipelines.models import AnswerResult, Status

# (a, b): the paired difference a - b is reported for these pairs of pipelines.
PAIRS = (("graphrag", "rag"), ("agent", "rag"), ("agent", "graphrag"))


def _clean(value: Any) -> Any:
    """JSON cannot carry NaN or infinity."""
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


def _block(raw: dict[str, Any]) -> MetricsBlock:
    return MetricsBlock(**{k: _clean(v) for k, v in raw.items()})


def list_runs(conn: Any) -> list[RunOut]:
    rows = conn.execute(
        """
        SELECT r.run_id, r.pipeline, r.split, r.question_version, r.started_at,
               r.finished_at, r.git_commit, r.notes,
               (SELECT COUNT(*) FROM results x WHERE x.run_id = r.run_id)
        FROM runs r ORDER BY COALESCE(r.finished_at, r.started_at) DESC, r.run_id
        """
    ).fetchall()
    return [
        RunOut(
            run_id=r[0],
            pipeline=r[1],
            split=r[2],
            question_version=r[3],
            started_at=r[4],
            finished_at=r[5],
            git_commit=r[6],
            notes=r[7],
            n_results=int(r[8]),
        )  # fmt: skip
        for r in rows
    ]


def _run_row(conn: Any, run_id: str) -> tuple | None:
    return conn.execute(
        "SELECT run_id, pipeline, split, question_version, git_commit FROM runs WHERE run_id = ?",
        [run_id],
    ).fetchone()


def load_score_rows(conn: Any, run_id: str) -> list[dict[str, Any]]:
    """Scores joined with the stored answer and the question's category, in the row
    shape the eval harness aggregates (the same one `scores.jsonl` has)."""
    rows = conn.execute(
        """
        SELECT s.qid, COALESCE(q.category, 'unknown'), s.correct, s.faithfulness,
               s.citation_accuracy, s.evidence_recall, s.failure_label, r.answer_json
        FROM scores s
        JOIN results r ON r.run_id = s.run_id AND r.qid = s.qid
        LEFT JOIN questions q ON q.qid = s.qid
        WHERE s.run_id = ? ORDER BY s.qid
        """,
        [run_id],
    ).fetchall()
    out = []
    for qid, category, correct, faith, cite, recall, label, answer_json in rows:
        res = AnswerResult.model_validate_json(answer_json)
        out.append(
            {
                "qid": qid,
                "category": category,
                "correct": float(correct or 0.0),
                "faithfulness": faith,
                "citation_accuracy": cite,
                "evidence_recall": recall,
                "failure_label": label,
                "abstained": res.status == Status.ABSTAINED,
                "error": res.status == Status.ERROR,
                "budget_exceeded": res.status == Status.BUDGET,
                "latency_ms": res.usage.latency_ms,
                "cost_usd": res.usage.cost_usd,
                "llm_calls": res.usage.llm_calls,
                "tool_calls": res.usage.tool_calls,
            }
        )
    return out


def run_metrics(conn: Any, run_id: str) -> RunMetrics | None:
    run = _run_row(conn, run_id)
    if run is None:
        return None
    rows = load_score_rows(conn, run_id)
    if not rows:
        return None
    summary = summarize(rows)
    return RunMetrics(
        run_id=run[0], pipeline=run[1], split=run[2], question_version=run[3], git_commit=run[4],
        overall=_block(summary["overall"]),
        by_category={c: _block(b) for c, b in summary["by_category"].items()},
    )  # fmt: skip


def get_result(conn: Any, run_id: str, qid: str) -> ResultOut | None:
    row = conn.execute(
        """
        SELECT r.answer_json, q.question, q.category,
               s.correct, s.faithfulness, s.citation_accuracy, s.evidence_recall,
               s.abstention_ok, s.failure_label, s.judge_reason, s.run_id
        FROM results r
        LEFT JOIN questions q ON q.qid = r.qid
        LEFT JOIN scores s ON s.run_id = r.run_id AND s.qid = r.qid
        WHERE r.run_id = ? AND r.qid = ?
        """,
        [run_id, qid],
    ).fetchone()
    if row is None:
        return None
    score = None
    if row[10] is not None:
        score = ScoreRow(
            correct=row[3], faithfulness=row[4], citation_accuracy=row[5], evidence_recall=row[6],
            abstention_ok=row[7], failure_label=row[8], judge_reason=row[9],
        )  # fmt: skip
    return ResultOut(
        run_id=run_id, qid=qid, question=row[1], category=row[2],
        result=AnswerResult.model_validate_json(row[0]), score=score,
    )  # fmt: skip


def list_questions(
    conn: Any, split: str | None = None, include_gold: bool = False
) -> list[QuestionOut]:
    """Gold answers are served for the dev split always, and for the test split
    only when asked for explicitly (local use)."""
    sql = (
        "SELECT qid, version, question, category, answer_type, split, verified, "
        "gold_answer_json, gold_evidence_json FROM questions"
    )
    params: list[Any] = []
    if split:
        sql += " WHERE split = ?"
        params.append(split)
    rows = conn.execute(sql + " ORDER BY qid", params).fetchall()
    out = []
    for qid, version, question, category, atype, qsplit, verified, gold, evidence in rows:
        show_gold = include_gold or qsplit == "dev"
        out.append(
            QuestionOut(
                qid=qid,
                version=version,
                question=question,
                category=category,
                answer_type=atype,
                split=qsplit,
                verified=bool(verified),
                gold_answer=json.loads(gold) if show_gold else None,
                gold_evidence=json.loads(evidence) if show_gold else None,
            )  # fmt: skip
        )
    return out


def _cell(run_id: str, row: dict[str, Any], result: AnswerResult) -> PipelineCell:
    return PipelineCell(
        run_id=run_id, status=result.status.value, answer_short=result.answer_short,
        correct=row["correct"], failure_label=row["failure_label"],
        cost_usd=result.usage.cost_usd, latency_ms=result.usage.latency_ms,
        tool_calls=result.usage.tool_calls,
    )  # fmt: skip


def _pair_entry(raw: dict[str, Any]) -> PairEntry:
    return PairEntry(
        n=raw["n"], diff=_clean(raw["diff"]), ci95=_clean(raw["ci95"]), verdict=raw["verdict"]
    )


def _leader(
    category: str, keys: list[str], metrics: dict[str, MetricsBlock], rows: dict[str, list[dict]]
) -> Leader:
    scored = [(k, metrics[k].correct_mean) for k in keys if metrics[k].n]
    ranked = sorted(((k, m) for k, m in scored if m is not None), key=lambda kv: -kv[1])
    if not ranked:
        return Leader(pipeline=None, mean=None, reason="no scored questions")
    top, runner = ranked[0], (ranked[1] if len(ranked) > 1 else None)
    if runner is None:
        return Leader(pipeline=top[0], mean=top[1], reason="only one pipeline has results")
    if top[1] == runner[1]:
        tied = [k for k, m in ranked if m == top[1]]
        return Leader(
            pipeline=None, mean=top[1], tied=tied, reason=f"tie on mean accuracy: {', '.join(tied)}"
        )

    def in_category(key: str) -> list[dict]:
        return [r for r in rows[key] if category == "overall" or r["category"] == category]

    verdict = compare_runs(in_category(top[0]), in_category(runner[0]), "correct")["overall"]
    clear = verdict["verdict"] == "A better"
    reason = (
        "paired difference excludes 0" if clear
        else f"unclear: {verdict['verdict']} (n={verdict['n']} paired questions)"
    )  # fmt: skip
    return Leader(pipeline=top[0], mean=top[1], runner_up=runner[0], clear=clear, reason=reason)


def compare_view(conn: Any, run_ids: dict[str, str]) -> CompareRunsOut:
    """The three pipelines' runs side by side: per-run metrics, one row per
    question, paired differences, and a per-category leader with a clear/unclear flag."""
    metrics: dict[str, RunMetrics] = {}
    rows: dict[str, list[dict]] = {}
    results: dict[str, dict[str, AnswerResult]] = {}
    for key, run_id in run_ids.items():
        m = run_metrics(conn, run_id)
        if m is None:
            continue
        metrics[key] = m
        rows[key] = load_score_rows(conn, run_id)
        stored = conn.execute(
            "SELECT qid, answer_json FROM results WHERE run_id = ?", [run_id]
        ).fetchall()
        results[key] = {q: AnswerResult.model_validate_json(a) for q, a in stored}

    categories_of = {r["qid"]: r["category"] for rs in rows.values() for r in rs}
    text_of = {q: t for q, t in conn.execute("SELECT qid, question FROM questions").fetchall()}
    questions = []
    for qid in sorted(categories_of):
        cells = {}
        for key, rs in rows.items():
            row = next((r for r in rs if r["qid"] == qid), None)
            if row is not None:
                cells[key] = _cell(run_ids[key], row, results[key][qid])
        questions.append(
            QuestionRow(
                qid=qid,
                question=text_of.get(qid, results[next(iter(cells))][qid].question),
                category=categories_of[qid],
                cells=cells,
            )  # fmt: skip
        )

    pairs = []
    for a, b in PAIRS:
        if a in rows and b in rows:
            raw = compare_runs(rows[a], rows[b], "correct")
            pairs.append(
                PairResult(
                    metric="correct",
                    a=a,
                    b=b,
                    overall=_pair_entry(raw["overall"]),
                    by_category={c: _pair_entry(e) for c, e in raw["by_category"].items()},
                )  # fmt: skip
            )

    keys = list(metrics)
    categories = sorted({c for m in metrics.values() for c in m.by_category})
    leaders = {
        c: _leader(
            c, keys, {k: metrics[k].by_category.get(c, MetricsBlock(n=0)) for k in keys}, rows
        )
        for c in categories
    }
    leaders["overall"] = _leader("overall", keys, {k: metrics[k].overall for k in keys}, rows)
    return CompareRunsOut(
        runs=run_ids, metrics=metrics, questions=questions, pairs=pairs, leaders=leaders
    )
