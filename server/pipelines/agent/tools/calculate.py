from pydantic import BaseModel, Field

from server.pipelines.agent.calculator import safe_eval
from server.pipelines.agent.tools.base import ToolContext, ToolResult, error

DESCRIPTION = (
    "Evaluate arithmetic exactly. Use for every sum, difference, percentage or unit "
    "conversion. Supports + - * / % ** ( ), sum([..]), min(), max(), round(), abs(). "
    "Numbers only: put each figure in the expression yourself."
)


class CalculateArgs(BaseModel):
    expression: str = Field(min_length=1, max_length=500)


def _format(value: float | int) -> str:
    return str(round(value, 10)) if isinstance(value, float) else str(value)


def run(ctx: ToolContext, args: CalculateArgs) -> ToolResult:
    expr = args.expression.strip()
    try:
        value = safe_eval(expr)
    except ZeroDivisionError:
        return error("division by zero")
    except (ValueError, SyntaxError, TypeError, OverflowError, RecursionError, MemoryError) as e:
        return error(f"cannot evaluate: {str(e)[:200]}")

    result = _format(value)
    label = ctx.log.add("tool_result", f"calc:{len(ctx.log) + 1}", f"calculate({expr}) = {result}")
    return ToolResult(ok=True, text=f"[{label}] {expr} = {result}", labels=[label])
