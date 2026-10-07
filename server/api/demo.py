"""Question validation and the cached demo answers.

Demo mode lets a judge run the whole UI with no API key: preset questions are
answered from `data/samples/cached_answers.jsonl`, which is built from real
stored runs (never written by hand)."""

import json
import logging
import re
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from server.api.deps import load_json_lines
from server.api.schemas import ExampleQuestion
from server.pipelines.models import AnswerResult

logger = logging.getLogger(__name__)

MAX_QUESTION_CHARS = 500
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_WHITESPACE = re.compile(r"\s+")
_TRAILING_PUNCTUATION = re.compile(r"[\s?.!]+$")


def validate_question(question: object) -> str:
    """Return the cleaned question or raise ValueError with a message for the user."""
    if not isinstance(question, str):
        raise ValueError("question must be a string")
    cleaned = _WHITESPACE.sub(" ", _CONTROL.sub("", question)).strip()
    if not cleaned:
        raise ValueError("question must not be empty")
    if len(cleaned) > MAX_QUESTION_CHARS:
        raise ValueError(f"question must be at most {MAX_QUESTION_CHARS} characters")
    return cleaned


def normalize_question(question: str) -> str:
    """The key cached answers are matched on: case, spacing and a trailing '?' do not matter."""
    return _TRAILING_PUNCTUATION.sub("", _WHITESPACE.sub(" ", question.strip().lower()))


def load_cache(path: Path) -> dict[str, dict[str, Any]]:
    entries: dict[str, dict[str, Any]] = {}
    for row in load_json_lines(path):
        question = row.get("question")
        results = row.get("results")
        if not isinstance(question, str) or not isinstance(results, dict):
            continue
        parsed: dict[str, AnswerResult] = {}
        try:
            for name, raw in results.items():
                parsed[name] = AnswerResult.model_validate(raw)
        except ValidationError as e:
            logger.warning(f"Skipping cached answer for {question!r}: {str(e)[:120]}")
            continue
        entries[normalize_question(question)] = {
            "question": question,
            "results": parsed,
            "source_runs": row.get("source_runs", {}),
        }
    return entries


def lookup(path: Path, question: str) -> dict[str, AnswerResult] | None:
    entry = load_cache(path).get(normalize_question(question))
    return entry["results"] if entry else None


def examples(path: Path) -> list[ExampleQuestion]:
    return [
        ExampleQuestion(question=e["question"], pipelines=sorted(e["results"]))
        for e in load_cache(path).values()
    ]


def build_cache_from_runs(
    conn: Any, run_ids: dict[str, str | list[str]], out_path: Path, limit: int | None = None
) -> int:
    """Write one cache line per question that has a stored answer in any of the
    given runs ({pipeline: run_id or [run_ids]}; with several, the first run that
    answered a question wins). Failed answers (status=error) are never cached, and a
    pipeline with no good stored answer is simply absent from that line. Returns the
    number of lines written."""
    texts = {q: t for q, t in conn.execute("SELECT qid, question FROM questions").fetchall()}
    by_question: dict[str, dict[str, Any]] = {}
    for pipeline, spec in run_ids.items():
        for run_id in [spec] if isinstance(spec, str) else spec:
            rows = conn.execute(
                "SELECT qid, answer_json FROM results WHERE run_id = ?", [run_id]
            ).fetchall()
            for qid, answer_json in rows:
                answer = json.loads(answer_json)
                if qid not in texts or answer.get("status") == "error":
                    continue
                entry = by_question.setdefault(
                    qid, {"question": texts[qid], "results": {}, "source_runs": {}}
                )
                if pipeline in entry["results"]:
                    continue
                entry["results"][pipeline] = answer
                entry["source_runs"][pipeline] = run_id

    entries = [by_question[q] for q in sorted(by_question)]
    if limit is not None:
        entries = entries[:limit]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("".join(json.dumps(e, sort_keys=True) + "\n" for e in entries))
    return len(entries)
