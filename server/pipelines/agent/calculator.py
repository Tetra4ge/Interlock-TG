import ast
import operator as op
from collections.abc import Callable
from typing import Any

MAX_EXPR_CHARS = 500
MAX_EXPONENT = 10
MAX_INT_BITS = 4096  # nested powers stay under the exponent cap yet grow without bound

BIN: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
    ast.Add: op.add,
    ast.Sub: op.sub,
    ast.Mult: op.mul,
    ast.Div: op.truediv,
    ast.Pow: op.pow,
    ast.Mod: op.mod,
}
UN: dict[type[ast.unaryop], Callable[[Any], Any]] = {ast.USub: op.neg, ast.UAdd: op.pos}


def _sum(*a: Any) -> Any:
    return sum(a[0]) if len(a) == 1 and isinstance(a[0], list) else sum(a)


FUNCS: dict[str, Callable[..., Any]] = {
    "sum": _sum,
    "min": min,
    "max": max,
    "round": round,
    "abs": abs,
}


def _check_size(value: Any) -> Any:
    if isinstance(value, int) and not isinstance(value, bool) and value.bit_length() > MAX_INT_BITS:
        raise ValueError("result too large")
    return value


def safe_eval(expr: str) -> float | int:
    """Evaluate arithmetic exactly. Only numbers, + - * / % **, unary signs,
    lists, and sum/min/max/round/abs are accepted: no names, attributes,
    subscripts, comprehensions, lambdas, strings or imports."""
    if not isinstance(expr, str) or not expr.strip():
        raise ValueError("empty expression")
    if len(expr) > MAX_EXPR_CHARS:
        raise ValueError("expression too long")
    tree = ast.parse(expr.strip(), mode="eval")

    def ev(n: ast.AST) -> Any:
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant):
            if isinstance(n.value, (int, float)) and not isinstance(n.value, bool):
                return n.value
            raise ValueError("only numbers are allowed")
        if isinstance(n, ast.BinOp) and type(n.op) in BIN:
            left, right = ev(n.left), ev(n.right)
            if isinstance(n.op, ast.Pow):
                if abs(right) > MAX_EXPONENT:
                    raise ValueError("exponent too large")
                if isinstance(left, int) and left.bit_length() * abs(right) > MAX_INT_BITS:
                    raise ValueError("result too large")
            return _check_size(BIN[type(n.op)](left, right))
        if isinstance(n, ast.UnaryOp) and type(n.op) in UN:
            return UN[type(n.op)](ev(n.operand))
        if isinstance(n, ast.List):
            return [ev(e) for e in n.elts]
        if (
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id in FUNCS
            and not n.keywords
        ):
            return FUNCS[n.func.id](*[ev(a) for a in n.args])
        raise ValueError(f"not allowed: {type(n).__name__}")

    result = ev(tree)
    if isinstance(result, (list, bool)) or not isinstance(result, (int, float)):
        raise ValueError("expression must evaluate to a number")
    return result
