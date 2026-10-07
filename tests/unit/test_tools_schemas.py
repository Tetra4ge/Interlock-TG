import json

import pytest

from server.parse.tokens import estimate_tokens
from server.pipelines.agent.evidence_log import EvidenceLog
from server.pipelines.agent.tools import TOOLS, execute_tool, tool_specs
from server.pipelines.agent.tools.base import ToolContext, cap_text, check_entity_id


@pytest.fixture
def ctx(tracer):  # type: ignore[no-untyped-def]
    return ToolContext("q", EvidenceLog(), tracer)


def test_all_six_tools_are_offered_with_graph_query_last() -> None:
    names = [s.name for s in tool_specs()]
    assert names == [
        "find_entity", "neighbors", "search_text", "calculate", "get_evidence", "graph_query"
    ]  # fmt: skip


def test_specs_can_exclude_a_tool() -> None:
    assert "graph_query" not in [s.name for s in tool_specs(frozenset({"graph_query"}))]


def test_schemas_come_from_the_argument_models_and_serialise() -> None:
    for spec in tool_specs():
        assert spec.description
        schema = spec.parameters
        assert schema["type"] == "object" and "properties" in schema
        json.dumps(schema)  # must be plain JSON for the provider
        assert spec.parameters == TOOLS[spec.name].args_model.model_json_schema()


def test_bounds_in_the_schema_match_the_plan() -> None:
    props = {s.name: s.parameters["properties"] for s in tool_specs()}
    assert props["neighbors"]["limit"]["anyOf"][0]["maximum"] == 60
    assert props["neighbors"]["hops"]["maximum"] == 2
    assert props["search_text"]["k"]["maximum"] == 8
    assert props["calculate"]["expression"]["maxLength"] == 500


def test_the_graph_query_description_lists_every_allowed_query() -> None:
    from server.pipelines.agent.guardrails import QUERY_REGISTRY

    description = TOOLS["graph_query"].description
    assert all(name in description for name in QUERY_REGISTRY)
    assert description.count("{") >= 3  # worked examples are present


# --- dispatcher: never raises --------------------------------------------


def test_unknown_tool_is_an_error_result(ctx: ToolContext) -> None:
    result = execute_tool(ctx, "run_gsql", {"q": "DELETE"})
    assert not result.ok and "unknown tool" in result.text and "find_entity" in result.text


@pytest.mark.parametrize("arguments", [None, [], "x", 5])
def test_non_object_arguments_are_an_error_result(ctx: ToolContext, arguments: object) -> None:
    assert not execute_tool(ctx, "calculate", arguments).ok


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("find_entity", {}),
        ("find_entity", {"name": "x" * 300}),
        ("neighbors", {"entity_id": "C:1", "hops": 5}),
        ("neighbors", {"entity_id": "C:1", "limit": 500}),
        ("neighbors", {"entity_id": "C:1", "rel_types": ["DROP_ALL"]}),
        ("search_text", {"query": "q", "k": 99}),
        ("search_text", {"query": "q", "company_id": "x; DROP"}),
        ("calculate", {"expression": ""}),
        ("get_evidence", {"ref_id": "a b; c"}),
    ],
)
def test_invalid_arguments_come_back_as_text(ctx: ToolContext, tool: str, arguments: dict) -> None:
    result = execute_tool(ctx, tool, arguments)
    assert not result.ok and result.text.startswith("error: invalid arguments")


def test_a_tool_that_crashes_is_contained(
    ctx: ToolContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(c: ToolContext, a: object) -> None:
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(TOOLS["calculate"], "run", boom)
    result = execute_tool(ctx, "calculate", {"expression": "1+1"})
    assert not result.ok and "RuntimeError: disk on fire" in result.text


def test_every_call_is_traced_as_a_tool_step(ctx: ToolContext) -> None:
    execute_tool(ctx, "calculate", {"expression": "2+2"})
    execute_tool(ctx, "run_gsql", {})
    steps = [s for s in ctx.tracer.steps if s.kind == "tool"]
    assert [s.name for s in steps] == ["calculate", "run_gsql"]
    assert steps[0].error is None and steps[1].error is not None


def test_output_is_capped_to_the_token_limit(
    ctx: ToolContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    from server.pipelines.agent.tools.base import ToolResult

    monkeypatch.setattr(
        TOOLS["calculate"], "run", lambda c, a: ToolResult(ok=True, text="word " * 20_000)
    )
    result = execute_tool(ctx, "calculate", {"expression": "1"})
    assert estimate_tokens(result.text) <= ctx.cfg.tool_output_tokens + 20
    assert "truncated" in result.text


def test_cap_text_leaves_short_text_alone() -> None:
    assert cap_text("short", 100) == "short"


@pytest.mark.parametrize("bad", ["Automobiles", "tata", "C:", "C:1; DROP", "X:1", "C:" + "a" * 70])
def test_entity_ids_must_look_like_entity_ids(bad: str) -> None:
    assert check_entity_id(bad) is not None


@pytest.mark.parametrize("good", ["C:TATASTEEL", "P:x67ebc80ea39b", "A:x1", "C:BAJAJ-AUTO"])
def test_valid_entity_ids_pass(good: str) -> None:
    assert check_entity_id(good) is None
