import json
from pathlib import Path

import pytest

from server.api import demo
from server.api.demo import (
    MAX_QUESTION_CHARS,
    build_cache_from_runs,
    examples,
    load_cache,
    lookup,
    normalize_question,
    validate_question,
)
from server.pipelines.models import Status
from tests.conftest import MemoryDB
from tests.unit.api_fixtures import answer_result, seed_question, seed_run


@pytest.mark.parametrize("bad", ["", "   ", "\n\t ", "\x00\x01", None, 5, ["q"]])
def test_empty_or_non_string_questions_are_rejected(bad: object) -> None:
    with pytest.raises(ValueError):
        validate_question(bad)


def test_overlong_questions_are_rejected_after_cleaning() -> None:
    assert len(validate_question("x" * MAX_QUESTION_CHARS)) == MAX_QUESTION_CHARS
    with pytest.raises(ValueError, match="at most 500"):
        validate_question("x" * (MAX_QUESTION_CHARS + 1))
    with pytest.raises(ValueError):
        validate_question("x" * 2000)


def test_control_characters_are_stripped_and_whitespace_collapsed() -> None:
    assert validate_question("  Who\x00 audits\n\tTata   Steel?\x07 ") == "Who audits Tata Steel?"
    assert validate_question("a" + "\x00" * 600) == "a"  # length is judged after cleaning


def test_normalisation_ignores_case_spacing_and_trailing_punctuation() -> None:
    a = normalize_question("Who audits  Tata Steel?")
    assert (
        a
        == normalize_question("who audits tata steel")
        == normalize_question(" WHO AUDITS TATA STEEL ?! ")
    )
    assert normalize_question("Who audits Tata Steel?") != normalize_question(
        "Who audits Tata Motors?"
    )


def _write(path: Path, *entries: dict) -> None:
    path.write_text("".join(json.dumps(e) + "\n" for e in entries))


def _entry(question: str, **pipelines: str) -> dict:
    return {
        "question": question,
        "results": {
            p: answer_result(p, short).model_dump(mode="json") for p, short in pipelines.items()
        },
        "source_runs": {p: f"run-{p}" for p in pipelines},
    }


def test_lookup_finds_a_cached_question_regardless_of_formatting(tmp_path: Path) -> None:
    path = tmp_path / "c.jsonl"
    _write(path, _entry("Who audits Tata Steel in FY2023-24?", rag="PwC", agent="PwC"))
    found = lookup(path, "who audits tata steel in fy2023-24")
    assert (
        found is not None and set(found) == {"rag", "agent"} and found["rag"].answer_short == "PwC"
    )
    assert lookup(path, "Who audits Tata Motors?") is None


def test_missing_file_is_an_empty_cache(tmp_path: Path) -> None:
    assert (
        load_cache(tmp_path / "none.jsonl") == {} and lookup(tmp_path / "none.jsonl", "q") is None
    )


def test_malformed_cache_lines_are_skipped(tmp_path: Path) -> None:
    path = tmp_path / "c.jsonl"
    good = _entry("good question", rag="a")
    bad_schema = {"question": "bad", "results": {"rag": {"pipeline": "rag"}}}
    path.write_text(
        "not json\n" + json.dumps(bad_schema) + "\n" + json.dumps({"results": {}}) + "\n"
        + json.dumps(good) + "\n"
    )  # fmt: skip
    assert [e["question"] for e in load_cache(path).values()] == ["good question"]


def test_examples_list_each_question_with_its_cached_pipelines(tmp_path: Path) -> None:
    path = tmp_path / "c.jsonl"
    _write(path, _entry("q one", rag="a", agent="b"), _entry("q two", rag="c"))
    listed = examples(path)
    assert [(e.question, e.pipelines) for e in listed] == [
        ("q one", ["agent", "rag"]),
        ("q two", ["rag"]),
    ]


def test_the_cache_is_built_from_stored_runs(memdb: MemoryDB, tmp_path: Path) -> None:
    for q in ("q1", "q2", "q3"):
        seed_question(memdb, q)
    row = lambda s: {"result": answer_result(short=s), "correct": 1.0}  # noqa: E731
    seed_run(memdb, "r-rag", "rag", rows={"q1": row("rag-1"), "q2": row("rag-2")})
    seed_run(memdb, "r-agent", "agent", rows={"q2": row("agent-2"), "q3": row("agent-3")})

    out = tmp_path / "samples" / "cached.jsonl"
    n = build_cache_from_runs(memdb, {"rag": "r-rag", "agent": "r-agent"}, out)

    assert n == 3
    cache = load_cache(out)
    q2 = cache[normalize_question("question q2")]
    assert set(q2["results"]) == {"rag", "agent"} and q2["source_runs"] == {
        "rag": "r-rag",
        "agent": "r-agent",
    }
    assert set(cache[normalize_question("question q1")]["results"]) == {
        "rag"
    }  # absent, not invented
    assert set(cache[normalize_question("question q3")]["results"]) == {"agent"}


def test_building_the_cache_respects_the_limit_and_skips_unknown_questions(
    memdb: MemoryDB, tmp_path: Path
) -> None:
    seed_question(memdb, "q1")
    seed_run(
        memdb,
        "r",
        "rag",
        rows={
            "q1": {"result": answer_result(), "correct": 1.0},
            "ghost": {"result": answer_result(), "correct": 1.0},
        },
    )
    out = tmp_path / "c.jsonl"
    assert build_cache_from_runs(memdb, {"rag": "r"}, out) == 1  # ghost has no question text
    seed_question(memdb, "q2")
    seed_run(
        memdb,
        "r2",
        "rag",
        rows={q: {"result": answer_result(), "correct": 1.0} for q in ("q1", "q2")},
    )
    assert build_cache_from_runs(memdb, {"rag": "r2"}, out, limit=1) == 1
    assert len(out.read_text().splitlines()) == 1


def test_cached_answers_keep_their_status(tmp_path: Path) -> None:
    path = tmp_path / "c.jsonl"
    entry = {
        "question": "q",
        "results": {"rag": answer_result(status=Status.ABSTAINED).model_dump(mode="json")},
    }
    _write(path, entry)
    assert lookup(path, "q")["rag"].status == Status.ABSTAINED  # type: ignore[index]
    assert demo.MAX_QUESTION_CHARS == 500
