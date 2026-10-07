from server.eval.models import GoldEvidence, Question
from server.eval.taxonomy import FAILURE_LABELS, classify_failure
from server.pipelines.models import AnswerResult, AnswerType, Status, Usage


def _q(answerable: bool = True, answer_type: AnswerType = AnswerType.ENTITY) -> Question:
    return Question(
        qid="q",
        version="v1",
        question="?",
        category="single_fact" if answerable else "unanswerable",
        answer_type=answer_type,
        gold_answer="x",
        gold_evidence=[GoldEvidence(doc_id="d", page=1)],
        split="test",
    )


def _r(status: Status) -> AnswerResult:
    return AnswerResult(
        pipeline="rag",
        question="?",
        answer_short="",
        answer_long="",
        answer_type=AnswerType.ENTITY,
        citations=[],
        evidence=[],
        trace=[],
        usage=Usage(
            tokens_in=0, tokens_out=0, cost_usd=0.0, latency_ms=1, llm_calls=1, tool_calls=0
        ),
        status=status,
    )


def test_correct_answer_has_no_failure() -> None:
    assert classify_failure(_q(), _r(Status.OK), correct=1.0) is None


def test_correct_abstention_on_unanswerable_has_no_failure() -> None:
    assert classify_failure(_q(answerable=False), _r(Status.ABSTAINED), correct=1.0) is None


def test_answering_an_unanswerable_question_is_hallucination() -> None:
    assert classify_failure(_q(answerable=False), _r(Status.OK), correct=0.0) == "hallucination"


def test_abstaining_on_an_answerable_question_is_wrong_abstention() -> None:
    assert classify_failure(_q(), _r(Status.ABSTAINED), correct=0.0) == "wrong_abstention"


def test_pipeline_error_is_bad_query() -> None:
    assert classify_failure(_q(), _r(Status.ERROR), correct=0.0) == "bad_query"


def test_wrong_with_unretrieved_evidence_is_retrieval_miss() -> None:
    label = classify_failure(_q(), _r(Status.OK), correct=0.0, evidence_recall=0.0)
    assert label == "retrieval_miss"


def test_wrong_number_with_evidence_is_arithmetic_error() -> None:
    label = classify_failure(
        _q(answer_type=AnswerType.NUMBER), _r(Status.OK), correct=0.0, evidence_recall=1.0
    )
    assert label == "arithmetic_error"


def test_unfaithful_wrong_answer_is_hallucination() -> None:
    label = classify_failure(
        _q(), _r(Status.OK), correct=0.0, faithfulness=0.0, evidence_recall=1.0
    )
    assert label == "hallucination"


def test_all_emitted_labels_are_in_the_taxonomy() -> None:
    emitted = {
        "hallucination",
        "wrong_abstention",
        "bad_query",
        "retrieval_miss",
        "arithmetic_error",
    }
    assert emitted <= FAILURE_LABELS


def test_unfaithful_answer_is_flagged_even_when_it_matches_gold() -> None:
    label = classify_failure(
        _q(), _r(Status.OK), correct=1.0, faithfulness=0.0, evidence_recall=1.0
    )
    assert label == "hallucination"


def test_faithful_correct_answer_stays_a_success() -> None:
    assert classify_failure(_q(), _r(Status.OK), correct=1.0, faithfulness=1.0) is None


def test_a_wrong_answer_that_exhausted_the_budget_is_a_budget_loop() -> None:
    assert (
        classify_failure(
            _q(), _r(Status.BUDGET), correct=0.0, faithfulness=None, evidence_recall=0.5
        )
        == "budget_loop"
    )


def test_a_correct_answer_that_exhausted_the_budget_is_still_a_success() -> None:
    assert classify_failure(_q(), _r(Status.BUDGET), correct=1.0) is None
