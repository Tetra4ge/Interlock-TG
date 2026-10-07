import json

import pytest

from server.llm.gateway import SpendCapExceeded
from server.llm.models import LLMResponse, ToolCall
from server.pipelines.agent import loop as loop_mod
from server.pipelines.agent.evidence_log import EvidenceLog
from server.pipelines.agent.loop import new_state, run_loop
from server.pipelines.agent.state import ANSWERED, BUDGET_EXCEEDED, ERROR, Budget
from server.pipelines.agent.tools import TOOLS
from server.pipelines.agent.tools.base import ToolResult


def call(tool: str, call_id: str = "c", **arguments: object) -> ToolCall:
    return ToolCall(id=call_id, name=tool, arguments=arguments)


def turn(*calls: ToolCall, text: str = "", tokens: int = 100) -> LLMResponse:
    return LLMResponse(content=text, tool_calls=list(calls), tokens_in=tokens, tokens_out=10)


class FakeLLM:
    """Plays a script of responses; once the script runs out it repeats `default`."""

    def __init__(self, *script: LLMResponse, default: LLMResponse | None = None) -> None:
        self.script, self.default = list(script), default
        self.requests: list = []

    def __call__(self, req):  # type: ignore[no-untyped-def]
        self.requests.append(req.model_copy(deep=True))
        if self.script:
            return self.script.pop(0)
        if self.default is None:
            raise AssertionError("the loop asked for more turns than scripted")
        return self.default


@pytest.fixture
def fake_tools(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """Replace tool execution with a counter so the loop is tested on its own."""
    executed: list[tuple[str, object]] = []

    def execute(ctx, name, arguments):  # type: ignore[no-untyped-def]
        executed.append((name, arguments))
        return ToolResult(ok=True, text=f"result of {name}", labels=["E1"])

    monkeypatch.setattr(loop_mod, "execute_tool", execute)
    return executed


def _run(llm: FakeLLM, monkeypatch, tracer, budget: Budget | None = None):  # type: ignore[no-untyped-def]
    monkeypatch.setattr(loop_mod, "call_llm", llm)
    budget = budget or Budget()
    state = run_loop(new_state("q", budget), EvidenceLog(), tracer, budget)
    return state


def test_a_model_that_answers_immediately_uses_no_steps(monkeypatch, tracer, fake_tools) -> None:  # type: ignore[no-untyped-def]
    state = _run(FakeLLM(turn(text="Ready: E1")), monkeypatch, tracer)
    assert state.status == ANSWERED and state.steps == [] and state.last_text == "Ready: E1"


def test_a_tool_then_an_answer(monkeypatch, tracer, fake_tools) -> None:  # type: ignore[no-untyped-def]
    llm = FakeLLM(turn(call("find_entity", name="Tata")), turn(text="Ready: E1"))
    state = _run(llm, monkeypatch, tracer)
    assert state.status == ANSWERED and [s.tool for s in state.steps] == ["find_entity"]
    assert state.steps[0].result_labels == ["E1"] and state.steps[0].n == 1
    assert fake_tools == [("find_entity", {"name": "Tata"})]


def test_a_model_that_always_calls_a_tool_stops_at_max_steps(
    monkeypatch, tracer, fake_tools
) -> None:  # type: ignore[no-untyped-def]
    counter = iter(range(1000))

    class Endless(FakeLLM):
        def __call__(self, req):  # type: ignore[no-untyped-def]
            self.requests.append(req)
            return turn(call("calculate", expression=f"{next(counter)}+1"))

    llm = Endless()
    state = _run(llm, monkeypatch, tracer, Budget(max_steps=4))
    assert state.status == BUDGET_EXCEEDED and state.stop_reason == "max_steps"
    assert len(state.steps) == 4 and len(llm.requests) == 4  # no wasted extra LLM call


def test_max_tokens_stops_the_loop(monkeypatch, tracer, fake_tools) -> None:  # type: ignore[no-untyped-def]
    llm = FakeLLM(default=turn(call("calculate", expression="1+1"), tokens=600))
    # identical calls are refused but still counted, so it ends on tokens, not steps
    state = _run(llm, monkeypatch, tracer, Budget(max_steps=50, max_tokens=1000))
    assert state.status == BUDGET_EXCEEDED and state.stop_reason == "max_tokens"


def test_timeout_stops_the_loop(monkeypatch, tracer, fake_tools) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(loop_mod, "call_llm", FakeLLM())
    budget = Budget(timeout_s=5)
    state = new_state("q", budget)
    state.started -= 6
    run_loop(state, EvidenceLog(), tracer, budget)
    assert state.status == BUDGET_EXCEEDED and state.stop_reason == "timeout"


def test_budget_exceeded_is_traced(monkeypatch, tracer, fake_tools) -> None:  # type: ignore[no-untyped-def]
    _run(FakeLLM(turn(call("a", expression="1"))), monkeypatch, tracer, Budget(max_steps=1))
    assert any(s.name == "budget_exceeded" and s.input_summary == "max_steps" for s in tracer.steps)


# --- repeats and parallel calls ---------------------------------------------


def test_an_identical_call_is_refused_and_counted(monkeypatch, tracer, fake_tools) -> None:  # type: ignore[no-untyped-def]
    same = call("search_text", query="auditor")
    llm = FakeLLM(turn(same), turn(same), turn(text="Ready"))
    state = _run(llm, monkeypatch, tracer)
    assert len(fake_tools) == 1  # executed once
    assert [s.ok for s in state.steps] == [True, False]
    assert "identical call already made" in state.steps[1].summary
    assert state.status == ANSWERED


def test_argument_order_does_not_hide_a_repeat(monkeypatch, tracer, fake_tools) -> None:  # type: ignore[no-untyped-def]
    llm = FakeLLM(
        turn(call("neighbors", entity_id="C:1", hops=1)),
        turn(call("neighbors", hops=1, entity_id="C:1")),
        turn(text="done"),
    )
    _run(llm, monkeypatch, tracer)
    assert len(fake_tools) == 1


def test_parallel_calls_run_in_order_and_each_is_answered(monkeypatch, tracer, fake_tools) -> None:  # type: ignore[no-untyped-def]
    llm = FakeLLM(
        turn(call("find_entity", "id-a", name="A"), call("find_entity", "id-b", name="B")),
        turn(text="Ready"),
    )
    state = _run(llm, monkeypatch, tracer)
    assert [a["name"] for _, a in fake_tools] == ["A", "B"]  # type: ignore[index]
    assistant = next(m for m in llm.requests[1].messages if m.role == "assistant")
    assert [c.id for c in assistant.tool_calls] == ["id-a", "id-b"]
    tool_msgs = [m for m in llm.requests[1].messages if m.role == "tool"]
    assert [m.tool_call_id for m in tool_msgs] == ["id-a", "id-b"]
    assert len(state.steps) == 2


def test_calls_beyond_the_step_budget_get_an_error_message_not_a_step(
    monkeypatch, tracer, fake_tools
) -> None:  # type: ignore[no-untyped-def]
    llm = FakeLLM(
        turn(*[call("find_entity", f"id-{i}", name=str(i)) for i in range(4)]),
    )
    state = _run(llm, monkeypatch, tracer, Budget(max_steps=2))
    assert len(fake_tools) == 2 and len(state.steps) == 2
    tool_msgs = [m for m in state.messages if m.role == "tool"]
    assert len(tool_msgs) == 4  # every id answered, or the next request would be rejected
    assert "step budget exhausted" in tool_msgs[-1].content
    assert state.status == BUDGET_EXCEEDED


# --- graph_query failures ----------------------------------------------------


def test_two_graph_query_failures_remove_the_tool(monkeypatch, tracer) -> None:  # type: ignore[no-untyped-def]
    def execute(ctx, name, arguments):  # type: ignore[no-untyped-def]
        return (
            ToolResult(ok=False, text="error: query failed")
            if name == "graph_query"
            else ToolResult(ok=True, text="ok")
        )

    monkeypatch.setattr(loop_mod, "execute_tool", execute)
    gq = lambda i: call("graph_query", f"g{i}", query_name="shared_directors", params={"n": i})  # noqa: E731
    llm = FakeLLM(
        turn(gq(1)), turn(gq(2)), turn(call("calculate", expression="1+1")), turn(text="done")
    )
    state = _run(llm, monkeypatch, tracer)

    offered = [[t.name for t in r.tools] for r in llm.requests]
    assert "graph_query" in offered[0] and "graph_query" in offered[1]
    assert "graph_query" not in offered[2] and "graph_query" not in offered[3]
    assert state.graph_query_failures == 2


def test_a_successful_graph_query_does_not_count(monkeypatch, tracer, fake_tools) -> None:  # type: ignore[no-untyped-def]
    llm = FakeLLM(turn(call("graph_query", query_name="x", params={})), turn(text="done"))
    state = _run(llm, monkeypatch, tracer)
    assert state.graph_query_failures == 0


# --- tool and LLM failures ---------------------------------------------------


def test_a_crashing_tool_is_returned_as_text_and_the_loop_continues(monkeypatch, tracer) -> None:  # type: ignore[no-untyped-def]
    def boom(ctx, args):  # type: ignore[no-untyped-def]
        raise RuntimeError("bug in tool")

    monkeypatch.setattr(TOOLS["calculate"], "run", boom)
    llm = FakeLLM(turn(call("calculate", expression="1+1")), turn(text="done"))
    state = _run(llm, monkeypatch, tracer)
    assert state.status == ANSWERED
    assert state.steps[0].ok is False and "bug in tool" in state.steps[0].summary
    tool_msg = next(m for m in llm.requests[1].messages if m.role == "tool")
    assert "RuntimeError" in tool_msg.content


def test_an_llm_failure_ends_the_loop_with_status_error(monkeypatch, tracer, fake_tools) -> None:  # type: ignore[no-untyped-def]
    class Down(FakeLLM):
        def __call__(self, req):  # type: ignore[no-untyped-def]
            raise ConnectionError("network down")

    state = _run(Down(), monkeypatch, tracer)
    assert state.status == ERROR and "network down" in (state.stop_reason or "")
    assert tracer.steps[-1].error is not None


def test_an_llm_response_with_an_error_ends_the_loop(monkeypatch, tracer, fake_tools) -> None:  # type: ignore[no-untyped-def]
    bad = LLMResponse(content="", tokens_in=0, tokens_out=0, error="bad request")
    state = _run(FakeLLM(bad), monkeypatch, tracer)
    assert state.status == ERROR and "bad request" in (state.stop_reason or "")


def test_the_spend_cap_propagates(monkeypatch, tracer, fake_tools) -> None:  # type: ignore[no-untyped-def]
    class Capped(FakeLLM):
        def __call__(self, req):  # type: ignore[no-untyped-def]
            raise SpendCapExceeded("cap")

    with pytest.raises(SpendCapExceeded):
        _run(Capped(), monkeypatch, tracer)


# --- conversation shape ------------------------------------------------------


def test_the_prompt_states_the_step_budget_and_tools_are_offered(
    monkeypatch, tracer, fake_tools
) -> None:  # type: ignore[no-untyped-def]
    llm = FakeLLM(turn(text="done"))
    _run(llm, monkeypatch, tracer, Budget(max_steps=5))
    req = llm.requests[0]
    assert (
        "at most 5 tool calls" in req.messages[0].content
        and "{max_steps}" not in req.messages[0].content
    )
    assert req.messages[1].content == "q"
    assert [t.name for t in req.tools][-1] == "graph_query"
    assert req.temperature == 0.0 and req.json_mode is False


def test_tokens_are_accumulated_across_turns(monkeypatch, tracer, fake_tools) -> None:  # type: ignore[no-untyped-def]
    llm = FakeLLM(turn(call("find_entity", name="A"), tokens=100), turn(text="done", tokens=200))
    state = _run(llm, monkeypatch, tracer)
    assert state.tokens_used == (100 + 10) + (200 + 10)


def test_the_loop_is_resumable_under_the_same_budget(monkeypatch, tracer, fake_tools) -> None:  # type: ignore[no-untyped-def]
    from server.llm.models import LLMMessage

    budget = Budget(max_steps=2)
    llm = FakeLLM(
        turn(call("a", expression="1")),
        turn(text="first"),
        turn(call("b", expression="2")),
        turn(call("c", expression="3")),
    )
    monkeypatch.setattr(loop_mod, "call_llm", llm)
    state = new_state("q", budget)
    log = EvidenceLog()
    run_loop(state, log, tracer, budget)
    assert state.status == ANSWERED and len(state.steps) == 1

    state.messages.append(LLMMessage(role="user", content="Verification failed; gather more."))
    run_loop(state, log, tracer, budget)
    assert len(state.steps) == 2 and state.status == BUDGET_EXCEEDED  # one step left, then the cap


def test_step_args_are_recorded_as_json_safe(monkeypatch, tracer, fake_tools) -> None:  # type: ignore[no-untyped-def]
    state = _run(FakeLLM(turn(call("find_entity", name="A")), turn(text="x")), monkeypatch, tracer)
    json.dumps(state.steps[0].model_dump())
