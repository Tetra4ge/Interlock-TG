from datetime import UTC, datetime

from server.common.logging import get_logger
from server.pipelines.models import TraceStep, Usage
from server.store.db import connect

logger = get_logger(__name__)

INPUT_SUMMARY_LIMIT = 500
OUTPUT_SUMMARY_LIMIT = 1000


class Tracer:
    """Records each pipeline step as a TraceStep and logs it to the `traces`
    table. Summaries are truncated so traces stay readable in the DB/CLI;
    full payloads are already in the LLM cache if you need them."""

    def __init__(self, request_id: str, pipeline: str) -> None:
        self.request_id = request_id
        self.pipeline = pipeline
        self.steps: list[TraceStep] = []

    def add(
        self,
        kind: str,
        name: str,
        input_summary: str,
        output_summary: str,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cost_usd: float = 0.0,
        latency_ms: int = 0,
        error: str | None = None,
    ) -> None:
        step = TraceStep(
            step=len(self.steps) + 1,
            kind=kind,
            name=name,
            input_summary=input_summary[:INPUT_SUMMARY_LIMIT],
            output_summary=output_summary[:OUTPUT_SUMMARY_LIMIT],
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            error=error,
        )
        self.steps.append(step)
        self._log_to_db(step)

    def usage(self, total_latency_ms: int) -> Usage:
        return Usage(
            tokens_in=sum(s.tokens_in for s in self.steps),
            tokens_out=sum(s.tokens_out for s in self.steps),
            cost_usd=sum(s.cost_usd for s in self.steps),
            latency_ms=total_latency_ms,
            llm_calls=sum(1 for s in self.steps if s.kind in ("llm", "verify")),
            tool_calls=sum(1 for s in self.steps if s.kind == "tool"),
        )

    def _log_to_db(self, step: TraceStep) -> None:
        conn = connect()
        try:
            conn.execute(
                """
                INSERT INTO traces
                (request_id, pipeline, step, kind, name, input_summary, output_summary,
                 tokens_in, tokens_out, cost_usd, latency_ms, error, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    self.request_id,
                    self.pipeline,
                    step.step,
                    step.kind,
                    step.name,
                    step.input_summary,
                    step.output_summary,
                    step.tokens_in,
                    step.tokens_out,
                    step.cost_usd,
                    step.latency_ms,
                    step.error,
                    datetime.now(UTC).isoformat(),
                ],
            )
            conn.commit()
        except Exception as e:
            logger.error(f"Failed to log trace step to DB: {e}")
        finally:
            conn.close()
