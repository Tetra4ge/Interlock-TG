import pytest

from server.pipelines.agent.calculator import safe_eval


@pytest.mark.parametrize(
    ("expr", "expected"),
    [
        ("12.5 + 3.25 * 2", 19.0),
        ("sum([1,2,3])", 6),
        ("sum(1, 2, 3)", 6),
        ("round(1/3, 4)", 0.3333),
        ("(100 - 80) / 80 * 100", 25.0),
        ("max(3, 9, 4) - min(3, 9, 4)", 6),
        ("abs(-4.5)", 4.5),
        ("-3 + +5", 2),
        ("2 ** 10", 1024),
        ("17 % 5", 2),
        ("48.20 * 100", pytest.approx(4820.0)),
        ("1 crore" if False else "1 * 10000000 / 100000", 100.0),
        ("sum([48.2, 12.5, 7.3])", pytest.approx(68.0)),
    ],
)
def test_valid_expressions(expr: str, expected: float) -> None:
    assert safe_eval(expr) == expected


@pytest.mark.parametrize(
    "expr",
    [
        "__import__('os')",
        "__import__('os').system('ls')",
        "open('x')",
        "a + 1",
        "(1).real",
        "(1).__class__",
        "[x for x in range(3)]",
        "lambda: 1",
        "9**9999",
        "2 ** -100",
        "'a' * 5",
        "'abc'",
        "True + 1",
        "None",
        "range(3)",
        "sum(range(3))",
        "[1, 2][0]",
        "round(1.5, ndigits=1)",
        "1 if 1 else 2",
        "eval('1')",
        "exec('x=1')",
        "print(1)",
        "x := 1",
        "1; 2",
        "",
        "   ",
        "import os",
        "[1, 2, 3]",
        "x" * 600,
    ],
)
def test_rejected_expressions(expr: str) -> None:
    with pytest.raises((ValueError, SyntaxError, TypeError)):
        safe_eval(expr)


def test_nested_powers_cannot_blow_up() -> None:
    expr = "9"
    for _ in range(12):
        expr = f"({expr}**10)"
    with pytest.raises(ValueError, match="too large"):
        safe_eval(expr)


def test_division_by_zero_is_an_error_not_a_crash() -> None:
    with pytest.raises(ZeroDivisionError):
        safe_eval("1/0")


def test_non_numeric_results_are_rejected() -> None:
    with pytest.raises(ValueError, match="number"):
        safe_eval("[1, 2]")


def test_non_string_input_is_rejected() -> None:
    with pytest.raises(ValueError):
        safe_eval(None)  # type: ignore[arg-type]


def test_deeply_nested_parentheses_do_not_crash_the_process() -> None:
    with pytest.raises((ValueError, SyntaxError, RecursionError, MemoryError)):
        safe_eval("(" * 400 + "1" + ")" * 400)
