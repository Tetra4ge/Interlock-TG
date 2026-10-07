"""Builders shared by the API tests."""

import json
from typing import Any

from server.pipelines.models import AnswerResult, AnswerType, Status, Usage
from tests.conftest import MemoryDB


def answer_result(
    pipeline: str = "rag",
    short: str = "a",
    status: Status = Status.OK,
    *,
    question: str = "q",
    cost: float = 0.0,
    latency_ms: int = 1,
    llm_calls: int = 1,
    tool_calls: int = 0,
    **extra: Any,
) -> AnswerResult:
    return AnswerResult(
        pipeline=pipeline,
        question=question,
        answer_short=short,
        answer_long=extra.pop("long", ""),
        answer_type=extra.pop("answer_type", AnswerType.ENTITY),
        citations=extra.pop("citations", []),
        evidence=extra.pop("evidence", []),
        trace=extra.pop("trace", []),
        status=status,
        usage=Usage(
            tokens_in=10, tokens_out=5, cost_usd=cost, latency_ms=latency_ms,
            llm_calls=llm_calls, tool_calls=tool_calls,
        ),
    )  # fmt: skip


def seed_question(
    db: MemoryDB, qid: str, category: str = "single_fact", split: str = "dev",
    question: str | None = None, gold: Any = "gold", gold_evidence: list | None = None,
) -> None:  # fmt: skip
    db.execute(
        "INSERT OR REPLACE INTO questions (qid, version, question, category, answer_type, "
        "gold_answer_json, gold_evidence_json, split, verified) "
        "VALUES (?, 'v1', ?, ?, 'entity', ?, ?, ?, 1)",
        [
            qid,
            question or f"question {qid}",
            category,
            json.dumps(gold),
            json.dumps(gold_evidence or []),
            split,
        ],
    )


def seed_run(
    db: MemoryDB, run_id: str, pipeline: str, split: str = "dev",
    rows: dict[str, dict[str, Any]] | None = None,
) -> None:  # fmt: skip
    """rows: qid -> {result: AnswerResult, correct, failure_label, faithfulness, ...}"""
    db.execute(
        "INSERT OR REPLACE INTO runs (run_id, pipeline, split, question_version, config_json, "
        "git_commit, started_at, finished_at) "
        "VALUES (?, ?, ?, 'v1', '{}', 'abc123', '2026-01-01', '2026-01-02')",
        [run_id, pipeline, split],
    )
    for qid, row in (rows or {}).items():
        db.execute(
            "INSERT OR REPLACE INTO results (run_id, qid, answer_json) VALUES (?, ?, ?)",
            [run_id, qid, row["result"].model_dump_json()],
        )
        db.execute(
            "INSERT OR REPLACE INTO scores (run_id, qid, correct, faithfulness, citation_accuracy, "
            "evidence_recall, abstention_ok, failure_label, judge_reason) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                run_id, qid, row.get("correct", 1.0), row.get("faithfulness"),
                row.get("citation_accuracy"), row.get("evidence_recall"),
                row.get("abstention_ok"), row.get("failure_label"), row.get("judge_reason"),
            ],
        )  # fmt: skip
    db.commit()
