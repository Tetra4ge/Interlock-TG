import json
from pathlib import Path

from server.llm.gateway import SpendCapExceeded, call_llm
from server.llm.models import LLMMessage, LLMRequest
from server.pipelines.agent.evidence_log import EvidenceLog
from server.pipelines.agent.state import (
    ANSWERED,
    BUDGET_EXCEEDED,
    ERROR,
    RUNNING,
    AgentState,
    Budget,
    Step,
)
from server.pipelines.agent.tools import execute_tool, tool_specs
from server.pipelines.agent.tools.base import ToolContext, ToolResult, error
from server.pipelines.common.answer import DEFAULT_MODEL
from server.pipelines.common.tracer import Tracer
from server.pipelines.config import AGENT, AgentConfig

SYSTEM_PROMPT_PATH = Path(__file__).resolve().parent / "prompts/agent_system_v1.md"
TURN_MAX_TOKENS = 800
SUMMARY_CHARS = 300
MAX_REJECTED_TURNS = 2
# Providers validate tool calls against the schema server-side and answer 400 when
# the model's call does not fit. That is the model's mistake, not an outage.
REJECTED_MARKER = "tool call validation failed"


def system_prompt(budget: Budget) -> str:
    return SYSTEM_PROMPT_PATH.read_text().replace("{max_steps}", str(budget.max_steps))


def new_state(question: str, budget: Budget) -> AgentState:
    return AgentState(
        question=question,
        messages=[
            LLMMessage(role="system", content=system_prompt(budget)),
            LLMMessage(role="user", content=question),
        ],
    )


def _call_key(name: str, arguments: object) -> str:
    return f"{name}:{json.dumps(arguments, sort_keys=True, default=str)}"


def run_loop(
    state: AgentState,
    log: EvidenceLog,
    tracer: Tracer,
    budget: Budget,
    cfg: AgentConfig = AGENT,
    model: str = DEFAULT_MODEL,
) -> AgentState:
    """Run the agent until it answers or a budget is spent. The model decides what
    to do; this code decides what is allowed and when to stop. Resumable: call it
    again after appending a message and the same budget keeps applying.

    Raises only SpendCapExceeded; every other failure ends the loop with
    status=error so the caller can still answer from the evidence gathered."""
    ctx = ToolContext(state.question, log, tracer, cfg)
    state.status, state.stop_reason = RUNNING, None

    while True:
        reason = state.check_budget(budget)
        if reason:
            state.status, state.stop_reason = BUDGET_EXCEEDED, reason
            tracer.add("verify", "budget_exceeded", reason, f"{len(state.steps)} steps")
            break

        exclude = (
            frozenset({"graph_query"})
            if state.graph_query_failures >= cfg.graph_query_max_failures
            else frozenset()
        )
        request = LLMRequest(
            provider="groq",
            model=model,
            messages=state.messages,
            tools=tool_specs(exclude),
            temperature=0.0,
            max_tokens=TURN_MAX_TOKENS,
        )
        try:
            resp = call_llm(request)
        except SpendCapExceeded:
            raise
        except Exception as e:
            if REJECTED_MARKER in str(e).lower() and state.rejected_turns < MAX_REJECTED_TURNS:
                state.rejected_turns += 1
                tracer.add(
                    "llm",
                    "agent_turn",
                    f"step {len(state.steps)}",
                    "",
                    error=f"rejected: {e}"[:400],
                )
                state.messages.append(
                    LLMMessage(
                        role="user",
                        content="Your last tool call was rejected because its arguments did not "
                        f"match the tool's schema ({str(e)[:300]}). Call the tool again with "
                        "arguments that match the schema.",
                    )
                )
                continue
            state.status, state.stop_reason = ERROR, f"llm: {e!r}"[:300]
            tracer.add("llm", "agent_turn", f"step {len(state.steps)}", "", error=state.stop_reason)
            break
        if resp.error:
            state.status, state.stop_reason = ERROR, f"llm: {resp.error}"[:300]
            tracer.add("llm", "agent_turn", f"step {len(state.steps)}", "", error=state.stop_reason)
            break

        state.tokens_used += resp.tokens_in + resp.tokens_out
        called = ", ".join(c.name for c in resp.tool_calls)
        tracer.add(
            "llm",
            "agent_turn",
            f"step {len(state.steps)}",
            resp.content[:500] or f"tool calls: {called}",
            resp.tokens_in,
            resp.tokens_out,
            resp.cost_usd,
            resp.latency_ms,
        )

        if not resp.tool_calls:
            state.messages.append(LLMMessage(role="assistant", content=resp.content))
            state.last_text = resp.content
            state.status = ANSWERED
            break

        state.messages.append(
            LLMMessage(role="assistant", content=resp.content, tool_calls=resp.tool_calls)
        )
        for call in resp.tool_calls:
            result = _handle_call(state, ctx, call.name, call.arguments, budget)
            # Every call id must be answered or the next request is rejected.
            state.messages.append(
                LLMMessage(role="tool", content=result.text, tool_call_id=call.id)
            )
    return state


def _handle_call(
    state: AgentState, ctx: ToolContext, name: str, arguments: object, budget: Budget
) -> ToolResult:
    if len(state.steps) >= budget.max_steps:
        # A model may request several calls in one turn; the extras are not run.
        return error("step budget exhausted; answer from the evidence you have")

    key = _call_key(name, arguments)
    state.repeat_counter[key] = state.repeat_counter.get(key, 0) + 1
    if state.repeat_counter[key] > 1:
        result = error("identical call already made; use its result")
    else:
        result = execute_tool(ctx, name, arguments)

    state.steps.append(
        Step(
            n=len(state.steps) + 1,
            tool=name,
            args=arguments if isinstance(arguments, dict) else {},
            ok=result.ok,
            result_labels=result.labels,
            summary=result.text[:SUMMARY_CHARS],
            latency_ms=result.latency_ms,
        )
    )
    if name == "graph_query" and not result.ok:
        state.graph_query_failures += 1
    return result
