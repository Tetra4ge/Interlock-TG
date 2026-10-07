import json
from pathlib import Path
from typing import Any

from server.eval.models import Question


def persist_run(conn: Any, run_dir: Path, questions: list[Question]) -> None:
    """Mirror a finished file-based run (config.json, results.jsonl,
    scores.jsonl) into the runs / results / scores / questions tables so the
    dashboard can read it. Idempotent: rerunning replaces the same rows."""
    config = json.loads((run_dir / "config.json").read_text())
    run_id = config["run_id"]

    conn.execute(
        "INSERT OR REPLACE INTO runs (run_id, pipeline, split, question_version, config_json, "
        "git_commit, started_at, finished_at, notes) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), ?)",
        [
            run_id,
            config["pipeline"],
            config["split"],
            config.get("questions_version") or "",
            json.dumps(config),
            config.get("git_commit"),
            config.get("started_at"),
            None,
        ],
    )

    for q in questions:
        conn.execute(
            "INSERT OR REPLACE INTO questions (qid, version, question, category, answer_type, "
            "gold_answer_json, gold_evidence_json, split, verified) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                q.qid,
                q.version,
                q.question,
                q.category,
                str(q.answer_type),
                json.dumps(q.gold_answer),
                json.dumps([e.model_dump() for e in q.gold_evidence]),
                q.split,
                int(q.verified),
            ],
        )

    for line in (run_dir / "results.jsonl").read_text().splitlines():
        if not line:
            continue
        rec = json.loads(line)
        conn.execute(
            "INSERT OR REPLACE INTO results (run_id, qid, answer_json) VALUES (?, ?, ?)",
            [run_id, rec["qid"], json.dumps(rec["result"])],
        )

    answerable = {q.qid: q.answerable for q in questions}
    for line in (run_dir / "scores.jsonl").read_text().splitlines():
        if not line:
            continue
        s = json.loads(line)
        abstention_ok = None
        if not answerable.get(s["qid"], True):
            abstention_ok = int(s["abstained"])
        conn.execute(
            "INSERT OR REPLACE INTO scores (run_id, qid, correct, faithfulness, citation_accuracy, "
            "evidence_recall, abstention_ok, failure_label, judge_reason) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                run_id,
                s["qid"],
                s["correct"],
                s.get("faithfulness"),
                s.get("citation_accuracy"),
                s.get("evidence_recall"),
                abstention_ok,
                s.get("failure_label"),
                s.get("judge_reason"),
            ],
        )
    conn.commit()
