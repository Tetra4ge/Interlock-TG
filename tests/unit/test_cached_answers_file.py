"""Guards on the committed demo cache, which judges run the UI against with no key."""

from server.api.demo import load_cache, normalize_question
from server.api.deps import CACHED_ANSWERS_PATH, load_json_lines
from server.api.schemas import PIPELINE_NAMES
from server.pipelines.models import Status


def test_the_shipped_cache_exists_and_every_line_is_valid() -> None:
    lines = load_json_lines(CACHED_ANSWERS_PATH)
    assert 10 <= len(lines) <= 20  # the plan asks for 10-20 showcase questions
    assert len(load_cache(CACHED_ANSWERS_PATH)) == len(lines)  # none skipped as malformed


def test_questions_are_unique_after_normalisation() -> None:
    questions = [e["question"] for e in load_json_lines(CACHED_ANSWERS_PATH)]
    assert len({normalize_question(q) for q in questions}) == len(questions)


def test_no_cached_answer_is_a_failure() -> None:
    for entry in load_cache(CACHED_ANSWERS_PATH).values():
        for result in entry["results"].values():
            assert result.status != Status.ERROR, entry["question"]


def test_only_known_pipelines_and_each_names_its_source_run() -> None:
    for entry in load_cache(CACHED_ANSWERS_PATH).values():
        assert entry["results"] and set(entry["results"]) <= set(PIPELINE_NAMES)
        assert set(entry["source_runs"]) == set(entry["results"])
        for name, result in entry["results"].items():
            assert result.pipeline == name
