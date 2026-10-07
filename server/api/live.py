"""Run pipelines for a live question.

Pipelines are ordinary blocking functions, so each runs in a worker thread and
`compare` gathers them. A pipeline normally returns an AnswerResult even on
failure; this module also covers the cases where it raises or hangs, so one bad
pipeline never breaks the other two."""

import asyncio
import logging
import time
from typing import Any

from server.api.deps import AppContext
from server.api.schemas import PIPELINE_NAMES
from server.common.ids import generate_id
from server.pipelines.models import AnswerResult, AnswerType, Status, TraceStep, Usage

logger = logging.getLogger(__name__)

PIPELINE_TIMEOUT_S = 300.0  # the agent can take minutes under free-tier rate limits


def new_request_id() -> str:
    return generate_id()


def failed_result(pipeline: str, question: str, error: str, latency_ms: int = 0) -> AnswerResult:
    return AnswerResult(
        pipeline=pipeline,
        question=question,
        answer_short="",
        answer_long="",
        answer_type=AnswerType.NOT_FOUND,
        citations=[],
        evidence=[],
        trace=[
            TraceStep(
                step=1,
                kind="verify",
                name="error",
                input_summary=question[:500],
                output_summary="",
                error=error[:500],
            )  # fmt: skip
        ],
        usage=Usage(
            tokens_in=0,
            tokens_out=0,
            cost_usd=0.0,
            latency_ms=latency_ms,
            llm_calls=0,
            tool_calls=0,
        ),
        status=Status.ERROR,
    )


def run_one(ctx: AppContext, name: str, question: str, request_id: str) -> AnswerResult:
    """Blocking. Never raises."""
    started = time.perf_counter()
    try:
        pipeline: Any = ctx.pipelines.get(name)
        if pipeline is None:
            return failed_result(name, question, f"pipeline {name!r} is not available")
        result: AnswerResult = pipeline.answer(question, request_id)
    except Exception as e:
        logger.exception(f"pipeline {name} raised")
        return failed_result(name, question, repr(e), int((time.perf_counter() - started) * 1000))
    ctx.save_adhoc_result(request_id, result)
    return result


async def run_compare(
    ctx: AppContext, question: str, request_id: str, timeout_s: float | None = None
) -> dict[str, AnswerResult]:
    timeout_s = PIPELINE_TIMEOUT_S if timeout_s is None else timeout_s

    async def guarded(name: str) -> AnswerResult:
        started = time.perf_counter()
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(run_one, ctx, name, question, request_id), timeout=timeout_s
            )
        except TimeoutError:
            return failed_result(
                name, question, f"timed out after {timeout_s:.0f}s",
                int((time.perf_counter() - started) * 1000),
            )  # fmt: skip

    results = await asyncio.gather(*(guarded(n) for n in PIPELINE_NAMES))
    return dict(zip(PIPELINE_NAMES, results, strict=True))
