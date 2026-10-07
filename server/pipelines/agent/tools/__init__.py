import time
from typing import Any

from pydantic import ValidationError

from server.llm.models import ToolSpec
from server.pipelines.agent.tools import (
    calculate,
    find_entity,
    get_evidence,
    graph_query,
    neighbors,
    search_text,
)
from server.pipelines.agent.tools.base import ToolContext, ToolDef, ToolResult, cap_text, error

# graph_query is last on purpose: models over-use the broadest tool when it is first.
TOOLS: dict[str, ToolDef] = {
    t.name: t
    for t in (
        ToolDef(name="find_entity", description=find_entity.DESCRIPTION,
                args_model=find_entity.FindEntityArgs, run=find_entity.run),
        ToolDef(name="neighbors", description=neighbors.DESCRIPTION,
                args_model=neighbors.NeighborsArgs, run=neighbors.run),
        ToolDef(name="search_text", description=search_text.DESCRIPTION,
                args_model=search_text.SearchTextArgs, run=search_text.run),
        ToolDef(name="calculate", description=calculate.DESCRIPTION,
                args_model=calculate.CalculateArgs, run=calculate.run),
        ToolDef(name="get_evidence", description=get_evidence.DESCRIPTION,
                args_model=get_evidence.GetEvidenceArgs, run=get_evidence.run),
        ToolDef(name="graph_query", description=graph_query.DESCRIPTION,
                args_model=graph_query.GraphQueryArgs, run=graph_query.run),
    )
}  # fmt: skip


def tool_specs(exclude: frozenset[str] = frozenset()) -> list[ToolSpec]:
    """JSON Schemas come from the argument models, so the schema the model sees is
    the schema that validates its call."""
    return [
        ToolSpec(
            name=t.name, description=t.description, parameters=t.args_model.model_json_schema()
        )
        for t in TOOLS.values()
        if t.name not in exclude
    ]


def execute_tool(ctx: ToolContext, name: str, arguments: Any) -> ToolResult:
    """Run one tool call. Never raises: every failure becomes an error result the
    model can read and recover from."""
    t0 = time.perf_counter()
    tool = TOOLS.get(name)
    if tool is None:
        result = error(f"unknown tool {str(name)[:60]!r}; available: {sorted(TOOLS)}")
    elif not isinstance(arguments, dict):
        result = error("arguments must be an object")
    else:
        try:
            result = tool.run(ctx, tool.args_model(**arguments))
        except ValidationError as e:
            result = error(f"invalid arguments: {_first_errors(e)}")
        except Exception as e:  # a tool bug must not end the question
            result = error(f"{name} failed: {type(e).__name__}: {str(e)[:200]}")

    result.text = cap_text(result.text, ctx.cfg.tool_output_tokens)
    result.latency_ms = int((time.perf_counter() - t0) * 1000)
    ctx.tracer.add(
        "tool",
        name,
        str(arguments)[:500],
        result.text[:500],
        latency_ms=result.latency_ms,
        error=None if result.ok else result.text[:300],
    )
    return result


def _first_errors(e: ValidationError) -> str:
    return "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()[:3])
