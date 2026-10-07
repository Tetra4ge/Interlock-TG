from pathlib import Path

from server.eval.models import GoldEvidence, Question
from server.eval.persist import persist_run
from server.eval.runner import run_eval
from server.pipelines.models import AnswerResult, AnswerType, Status, Usage


class _Fake:
    def answer(self, question: str, request_id: str) -> AnswerResult:
        return AnswerResult(
            pipeline="fake",
            question=question,
            answer_short="Sanjiv Bajaj",
            answer_long="",
            answer_type=AnswerType.ENTITY,
            citations=[],
            evidence=[],
            trace=[],
            usage=Usage(
                tokens_in=0, tokens_out=0, cost_usd=0.0, latency_ms=1, llm_calls=1, tool_calls=0
            ),
            status=Status.ABSTAINED,
        )


def _qs() -> list[Question]:
    return [
        Question(
            qid="a",
            version="v1",
            question="who?",
            category="single_fact",
            answer_type=AnswerType.ENTITY,
            gold_answer="Sanjiv Bajaj",
            gold_evidence=[GoldEvidence(doc_id="d", page=1)],
            split="test",
            verified=True,
        ),
        Question(
            qid="u",
            version="v1",
            question="nothing?",
            category="unanswerable",
            answer_type=AnswerType.NOT_FOUND,
            gold_answer=None,
            split="test",
            verified=True,
        ),
    ]


def test_persist_writes_runs_results_scores_and_questions(tmp_path: Path, memdb) -> None:
    run_eval("fake", "test", run_id="p1", pipeline=_Fake(), questions=_qs(), runs_dir=tmp_path)
    persist_run(memdb, tmp_path / "p1", _qs())

    assert memdb.execute("SELECT pipeline, split FROM runs WHERE run_id='p1'").fetchone() == (
        "fake",
        "test",
    )
    assert memdb.execute("SELECT COUNT(*) FROM results WHERE run_id='p1'").fetchone()[0] == 2
    assert memdb.execute("SELECT COUNT(*) FROM scores WHERE run_id='p1'").fetchone()[0] == 2
    assert memdb.execute("SELECT COUNT(*) FROM questions").fetchone()[0] == 2


def test_abstention_is_recorded_only_for_unanswerable(tmp_path: Path, memdb) -> None:
    run_eval("fake", "test", run_id="p2", pipeline=_Fake(), questions=_qs(), runs_dir=tmp_path)
    persist_run(memdb, tmp_path / "p2", _qs())
    rows = dict(memdb.execute("SELECT qid, abstention_ok FROM scores WHERE run_id='p2'").fetchall())
    assert rows == {"a": None, "u": 1}


def test_rerunning_persist_replaces_rows(tmp_path: Path, memdb) -> None:
    run_eval("fake", "test", run_id="p3", pipeline=_Fake(), questions=_qs(), runs_dir=tmp_path)
    persist_run(memdb, tmp_path / "p3", _qs())
    persist_run(memdb, tmp_path / "p3", _qs())
    assert memdb.execute("SELECT COUNT(*) FROM scores WHERE run_id='p3'").fetchone()[0] == 2
