"""Failure taxonomy for evaluation (TRD §8, scores.failure_label).

A deterministic, best-effort classifier: given a scored answer it assigns
one failure label, or None when the answer is a success. It only uses
signals available for the pipelines that exist today (status, abstention,
correctness, faithfulness, evidence recall, answer type). The deeper
graph-specific labels -- entity_link_error, missed_hop, temporal_error --
need the GraphRAG/agent pipelines and a manual or judge review to assign
reliably, so they are defined here but not auto-detected yet.
"""

from server.eval.models import Question
from server.pipelines.models import AnswerResult, AnswerType, Status

# The full taxonomy, kept here so the dashboard and manual review share one
# vocabulary even though the auto-classifier only emits a subset.
FAILURE_LABELS = frozenset(
    {
        "retrieval_miss",
        "entity_link_error",
        "missed_hop",
        "temporal_error",
        "arithmetic_error",
        "hallucination",
        "wrong_abstention",
        "bad_query",
        "budget_loop",
        "data_error",
    }
)


def classify_failure(
    q: Question,
    r: AnswerResult,
    *,
    correct: float,
    faithfulness: float | None = None,
    evidence_recall: float | None = None,
) -> str | None:
    """Return a failure label, or None if the answer counts as a success.

    Success = a correct answerable answer, or a correct abstention on an
    unanswerable question.
    """
    abstained = r.status == Status.ABSTAINED
    errored = r.status == Status.ERROR

    # A pipeline that could not produce an answer at all.
    if errored:
        return "bad_query"

    if not q.answerable:
        # Answering a question that has no answer is a hallucination;
        # abstaining is the correct behavior.
        return None if abstained else "hallucination"

    # Answerable from here on.
    if abstained:
        return "wrong_abstention"

    # An answer that matches gold but is not supported by the evidence it was
    # shown is still a hallucination; checking correctness first would hide it.
    if faithfulness is not None and faithfulness < 1.0:
        return "hallucination"

    if correct >= 1.0:
        return None

    # Answerable, answered, but wrong -- attribute as best we can.
    if evidence_recall == 0.0:
        # The gold evidence was never retrieved.
        return "retrieval_miss"

    if q.answer_type == AnswerType.NUMBER:
        # Evidence was present but the number came out wrong.
        return "arithmetic_error"

    if evidence_recall is None:
        # No gold evidence to check against; a retrieval miss is the most
        # likely cause for a plain RAG answer.
        return "retrieval_miss"

    # Evidence was retrieved but the answer is still wrong.
    return "hallucination"
