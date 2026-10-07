import time

from server.llm.gateway import SpendCapExceeded
from server.llm.models import LLMMessage
from server.pipelines.agent.evidence_log import EvidenceLog, question_similarity, recent_labels
from server.pipelines.agent.loop import new_state, run_loop
from server.pipelines.agent.state import (
    BUDGET_EXCEEDED,
    ERROR,
    RUNNING,
    AgentState,
    Budget,
)
from server.pipelines.agent.verifier import VerifyResult, verify_answer
from server.pipelines.base import register
from server.pipelines.common.answer import final_answer
from server.pipelines.common.render import LabeledEvidence, assign_labels
from server.pipelines.common.result import build_result, elapsed_ms, error_result
from server.pipelines.common.tracer import Tracer
from server.pipelines.config import AGENT, RETRIEVAL, AgentConfig
from server.pipelines.models import AnswerResult, AnswerType, ModelAnswer, Status

NOT_FOUND = ModelAnswer(
    answer_type=AnswerType.NOT_FOUND,
    answer_short="not found in the data",
    answer_long="The evidence gathered does not support an answer to this question.",
    citations=[],
)


def _draft(
    state: AgentState, log: EvidenceLog, tracer: Tracer, question: str, extra: str = ""
) -> tuple[ModelAnswer | None, dict[str, LabeledEvidence], str | None]:
    """The shared final answer over the evidence log, within the shared budget."""
    items, provenance = log.prioritized(
        RETRIEVAL.evidence_token_budget,
        state.last_text,
        recent_labels(state.steps),
        relevance=lambda texts: question_similarity(question, texts),
    )
    labels = assign_labels(items, provenance)
    answer, err = final_answer(tracer, question, labels, extra_instructions=extra)
    return answer, labels, err


def _failure_note(verdict: VerifyResult) -> str:
    return "; ".join(c.claim for c in verdict.unsupported)


def verify_and_repair(
    question: str,
    state: AgentState,
    log: EvidenceLog,
    tracer: Tracer,
    budget: Budget,
    cfg: AgentConfig,
    answer: ModelAnswer,
    labels: dict[str, LabeledEvidence],
) -> tuple[ModelAnswer, dict[str, LabeledEvidence]]:
    """Plan step 9. All supported -> done. Otherwise, if budget remains, one more
    agent cycle to gather evidence and a fresh draft; if claims are still
    unsupported, redraft keeping only supported claims (or not_found if none)."""
    if answer.answer_type == AnswerType.NOT_FOUND:
        return answer, labels  # nothing to verify

    verdict = verify_answer(tracer, answer, labels)
    if verdict.ok or verdict.failed:
        return answer, labels

    if state.status != ERROR and state.check_budget(budget) is None:
        tracer.add("verify", "repair_cycle", _failure_note(verdict), "one more agent cycle")
        state.messages.append(
            LLMMessage(
                role="user",
                content=f"Verification failed for: {_failure_note(verdict)}. "
                "Gather evidence for these or leave them out.",
            )
        )
        state.status = RUNNING
        run_loop(state, log, tracer, budget, cfg)
        redraft, new_labels, err = _draft(state, log, tracer, question)
        if redraft is not None and err is None:
            answer, labels = redraft, new_labels
            if answer.answer_type == AnswerType.NOT_FOUND:
                return answer, labels
            verdict = verify_answer(tracer, answer, labels)
            if verdict.ok or verdict.failed:
                return answer, labels

    supported = [c.claim for c in verdict.supported]
    if not supported:
        tracer.add("verify", "dropped_unsupported", _failure_note(verdict), "not_found")
        return NOT_FOUND, labels

    extra = (
        "Some claims in your previous draft were not supported by the evidence. Write the "
        "answer again using ONLY these supported claims:\n- "
        + "\n- ".join(supported)
        + "\nDo not state: "
        + _failure_note(verdict)
        + "\nIf the question can no longer be answered, return answer_type not_found."
    )
    trimmed, trimmed_labels, err = _draft(state, log, tracer, question, extra)
    tracer.add("verify", "dropped_unsupported", _failure_note(verdict), "redrafted", error=err)
    if trimmed is None:
        return NOT_FOUND, labels
    return trimmed, trimmed_labels


class AgentPipeline:
    """Plan, call tools under guardrails and budgets, answer from the labelled
    evidence with the shared final answer, then verify the answer's claims."""

    name = "agent"

    def __init__(self, cfg: AgentConfig = AGENT) -> None:
        self.cfg = cfg

    def answer(self, question: str, request_id: str) -> AnswerResult:
        tr = Tracer(request_id, self.name)
        start = time.perf_counter()
        try:
            budget = Budget.from_config(self.cfg)
            state, log = new_state(question, budget), EvidenceLog()
            run_loop(state, log, tr, budget, self.cfg)
            if state.status == ERROR and len(log) == 0:
                # Nothing was gathered, so an abstention would hide a failure.
                return error_result(
                    self.name, question, tr, state.stop_reason or "agent_error", start
                )

            draft, labels, err = _draft(state, log, tr, question)
            if draft is None:
                return error_result(self.name, question, tr, err or "unknown_error", start)
            if self.cfg.verify_enabled:
                draft, labels = verify_and_repair(
                    question, state, log, tr, budget, self.cfg, draft, labels
                )

            result = build_result(self.name, question, tr, draft, labels, start)
            if state.status == BUDGET_EXCEEDED and draft.answer_type != AnswerType.NOT_FOUND:
                result.status = Status.BUDGET  # keeps its status even with a partial answer
            result.usage.latency_ms = elapsed_ms(start)
            return result
        except Exception as e:
            reason = "spend_cap" if isinstance(e, SpendCapExceeded) else repr(e)
            return error_result(self.name, question, tr, reason, start)


register(AgentPipeline())
