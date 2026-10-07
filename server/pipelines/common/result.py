import time

from server.pipelines.common.citations import validate_citations
from server.pipelines.common.render import LabeledEvidence
from server.pipelines.common.tracer import Tracer
from server.pipelines.models import AnswerResult, AnswerType, ModelAnswer, Status


def elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def error_result(
    pipeline: str, question: str, tracer: Tracer, error: str, start: float
) -> AnswerResult:
    if not tracer.steps or tracer.steps[-1].error != error:
        tracer.add("verify", "error", question, "", error=error)
    return AnswerResult(
        pipeline=pipeline,
        question=question,
        answer_short="",
        answer_long="",
        answer_type=AnswerType.NOT_FOUND,
        citations=[],
        evidence=[],
        trace=tracer.steps,
        usage=tracer.usage(elapsed_ms(start)),
        status=Status.ERROR,
    )


def build_result(
    pipeline: str,
    question: str,
    tracer: Tracer,
    model_answer: ModelAnswer,
    labels: dict[str, LabeledEvidence],
    start: float,
) -> AnswerResult:
    """Post-processing shared by every pipeline: resolve the model's citation
    labels to real (doc, page, quote), then package the AnswerResult."""
    citations, flags = validate_citations(model_answer.citations, labels)
    tracer.add(
        "verify", "validate_citations", f"{len(model_answer.citations)} citations", str(flags)
    )
    status = Status.ABSTAINED if model_answer.answer_type == AnswerType.NOT_FOUND else Status.OK
    return AnswerResult(
        pipeline=pipeline,
        question=question,
        answer_short=model_answer.answer_short,
        answer_long=model_answer.answer_long,
        answer_type=model_answer.answer_type,
        citations=citations,
        evidence=[le.item for le in labels.values()],
        trace=tracer.steps,
        usage=tracer.usage(elapsed_ms(start)),
        status=status,
    )
