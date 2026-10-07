import contextlib
import json
from pathlib import Path

from server.eval.models import Question
from server.eval.runner import run_eval
from server.pipelines.models import AnswerResult, AnswerType, Status, Usage


class _CountingPipeline:
    def __init__(self, fail_after: int | None = None) -> None:
        self.calls: list[str] = []
        self.fail_after = fail_after

    def answer(self, question: str, request_id: str) -> AnswerResult:
        if self.fail_after is not None and len(self.calls) >= self.fail_after:
            raise KeyboardInterrupt
        self.calls.append(request_id)
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
                tokens_in=0, tokens_out=0, cost_usd=0.0, latency_ms=5, llm_calls=1, tool_calls=0
            ),
            status=Status.OK,
        )


def _questions(n: int) -> list[Question]:
    return [
        Question(
            qid=f"Q-{i}",
            version="v1",
            question=f"question {i}",
            category="single_fact",
            answer_type=AnswerType.ENTITY,
            gold_answer="Sanjiv Bajaj",
            gold_evidence=[],
            split="test",
            verified=True,
        )
        for i in range(n)
    ]


def test_resume_completes_without_duplicates(tmp_path: Path) -> None:
    qs = _questions(5)

    crashing = _CountingPipeline(fail_after=3)
    with contextlib.suppress(KeyboardInterrupt):
        run_eval("fake", "test", run_id="r1", pipeline=crashing, questions=qs, runs_dir=tmp_path)

    resumed = _CountingPipeline()
    summary = run_eval(
        "fake", "test", run_id="r1", pipeline=resumed, questions=qs, runs_dir=tmp_path
    )

    lines = (tmp_path / "r1" / "results.jsonl").read_text().splitlines()
    qids = [json.loads(line)["qid"] for line in lines]
    assert sorted(qids) == sorted({q.qid for q in qs})
    assert len(resumed.calls) == 2
    assert summary["overall"]["n"] == 5
    assert summary["overall"]["correct_mean"] == 1.0


def test_judge_scores_only_answered_answerable_questions(tmp_path: Path) -> None:
    from server.eval.judge import JudgeResult

    seen: list[str] = []

    def judge(question: str, answer_long: str, evidence_texts: list[str]) -> JudgeResult:
        seen.append(question)
        return JudgeResult(faithfulness=0.0, reason="unsupported")

    qs = _questions(2)
    summary = run_eval(
        "fake",
        "test",
        run_id="rj",
        pipeline=_CountingPipeline(),
        questions=qs,
        runs_dir=tmp_path,
        judge=judge,
    )
    # The fake answer has no evidence, so the judge is never called and
    # faithfulness stays unscored rather than being counted as a failure.
    assert seen == []
    assert summary["overall"]["faithfulness_mean"] is None


class _EvidencePipeline(_CountingPipeline):
    def answer(self, question: str, request_id: str) -> AnswerResult:
        from server.pipelines.models import EvidenceItem

        base = super().answer(question, request_id)
        return base.model_copy(
            update={"evidence": [EvidenceItem(kind="chunk", ref_id="c1", text="Sanjiv Bajaj")]}
        )


def test_judge_verdict_reaches_the_score(tmp_path: Path) -> None:
    from server.eval.judge import JudgeResult

    def judge(question: str, answer_long: str, evidence_texts: list[str]) -> JudgeResult:
        assert evidence_texts == ["Sanjiv Bajaj"]
        return JudgeResult(faithfulness=0.0, reason="unsupported")

    summary = run_eval(
        "fake",
        "test",
        run_id="rj2",
        pipeline=_EvidencePipeline(),
        questions=_questions(2),
        runs_dir=tmp_path,
        judge=judge,
    )
    assert summary["overall"]["faithfulness_mean"] == 0.0
    assert summary["overall"]["failures"] == {"hallucination": 2}


class _AgentLikePipeline:
    """Reports tool calls, and a budget-exceeded status on the second question."""

    def __init__(self) -> None:
        self.n = 0

    def answer(self, question: str, request_id: str) -> AnswerResult:
        self.n += 1
        exceeded = self.n == 2
        return AnswerResult(
            pipeline="agent",
            question=question,
            answer_short="Sanjiv Bajaj" if not exceeded else "Someone Else",
            answer_long="",
            answer_type=AnswerType.ENTITY,
            citations=[],
            evidence=[],
            trace=[],
            usage=Usage(
                tokens_in=0, tokens_out=0, cost_usd=0.01, latency_ms=5, llm_calls=4, tool_calls=3
            ),
            status=Status.BUDGET if exceeded else Status.OK,
        )


def test_steps_and_budget_exceeded_rate_are_reported(tmp_path: Path) -> None:
    summary = run_eval(
        "agent", "test", run_id="r-agent", pipeline=_AgentLikePipeline(),
        questions=_questions(4), runs_dir=tmp_path,
    )  # fmt: skip
    overall = summary["overall"]
    assert overall["tool_calls_mean"] == 3
    assert overall["budget_exceeded_rate"] == 0.25
    # a wrong answer that hit the budget is labelled as such
    assert overall["failures"] == {"budget_loop": 1}
    scores = [
        json.loads(line) for line in (tmp_path / "r-agent/scores.jsonl").read_text().splitlines()
    ]
    assert [s["budget_exceeded"] for s in scores] == [False, True, False, False]


def test_a_run_without_tool_calls_still_summarises(tmp_path: Path) -> None:
    summary = run_eval(
        "fake", "test", run_id="r-plain", pipeline=_CountingPipeline(),
        questions=_questions(2), runs_dir=tmp_path,
    )  # fmt: skip
    assert summary["overall"]["tool_calls_mean"] == 0
    assert summary["overall"]["budget_exceeded_rate"] == 0
