"""Seeded fuzzing of the two components that stand between untrusted model output
and the graph / the interpreter. Deterministic, so a failure is reproducible."""

import random
import re
import string

import pytest

from server.pipelines.agent.calculator import safe_eval
from server.pipelines.agent.guardrails import ID_RE, QUERY_REGISTRY, check_graph_call

NASTY = string.ascii_letters + string.digits + ":-_|" + " \t\n\r\x00;\"'`(){}[]<>=*&$%#@!\\/.,"


def _random_string(rng: random.Random) -> str:
    return "".join(rng.choice(NASTY) for _ in range(rng.randint(0, 80)))


def test_guardrails_accept_a_string_only_if_it_fully_matches_the_id_pattern() -> None:
    rng = random.Random(1234)
    for _ in range(3000):
        value = _random_string(rng)
        ok, _, _ = check_graph_call("stake_aggregate", {"company_id": value})
        assert ok == bool(ID_RE.fullmatch(value)), repr(value)


def test_every_accepted_value_is_free_of_query_syntax() -> None:
    rng = random.Random(99)
    accepted = 0
    for _ in range(4000):
        value = _random_string(rng)
        ok, _, args = check_graph_call("path_between", {"source_id": value, "target_id": "C:1"})
        if ok:
            accepted += 1
            assert re.fullmatch(r"[A-Za-z0-9_:\-|]{1,64}", args["source_id"])
            assert not set(args["source_id"]) & set(" \t\n\r\x00;\"'`(){}[]<>=*&$%#@!\\/.,")
    assert accepted > 0  # the fuzzer does produce valid ids, so the check is not vacuous


def test_unknown_query_names_never_pass() -> None:
    rng = random.Random(7)
    for _ in range(2000):
        name = _random_string(rng)
        if name in QUERY_REGISTRY:
            continue
        assert check_graph_call(name, {})[0] is False


def test_random_json_shaped_params_never_crash_the_guardrails() -> None:
    rng = random.Random(5)
    values = [None, 0, -1, 10**9, 1.5, True, "", "C:1", [], ["C:1"], {}, {"a": 1}, [[]], "x" * 100]
    for _ in range(3000):
        name = rng.choice(list(QUERY_REGISTRY))
        params = {
            rng.choice(["company_id", "company_ids", "source_id", "target_id", "max_hops", "hops",
                        "fiscal_year", "entity_ids", "junk"]): rng.choice(values)
            for _ in range(rng.randint(0, 4))
        }  # fmt: skip
        ok, reason, validated = check_graph_call(name, params)
        assert isinstance(ok, bool) and isinstance(reason, str)
        assert validated == {} if not ok else isinstance(validated, dict)


ATOMS = ["1", "2.5", "10", "0", "-3", "100", "7", "x", "a", "'s'", "True", "None", "[1,2]", "()"]
OPS = [
    "+",
    "-",
    "*",
    "/",
    "**",
    "%",
    ",",
    "(",
    ")",
    "[",
    "]",
    ".",
    " if ",
    " for ",
    ":=",
    "lambda ",
]
FUNCS = ["sum", "min", "max", "round", "abs", "eval", "open", "__import__", "print", "len"]


def _random_expr(rng: random.Random) -> str:
    parts = []
    for _ in range(rng.randint(1, 14)):
        parts.append(rng.choice([rng.choice(ATOMS), rng.choice(OPS), rng.choice(FUNCS) + "("]))
    return "".join(parts)


def test_the_calculator_only_ever_fails_cleanly() -> None:
    allowed = (ValueError, SyntaxError, TypeError, ZeroDivisionError, OverflowError)
    rng = random.Random(2024)
    evaluated = 0
    for _ in range(6000):
        expr = _random_expr(rng)
        try:
            result = safe_eval(expr)
        except allowed:
            continue
        evaluated += 1
        assert isinstance(result, (int, float)) and not isinstance(result, bool), expr
    assert evaluated > 0


@pytest.mark.parametrize("name", ["eval", "open", "__import__", "print", "len", "exec", "compile"])
def test_no_builtin_other_than_the_whitelist_is_callable(name: str) -> None:
    with pytest.raises((ValueError, SyntaxError, TypeError)):
        safe_eval(f"{name}(1)")


def test_the_calculator_agrees_with_python_on_random_arithmetic() -> None:
    rng = random.Random(8)
    for _ in range(1500):
        a, b, c = (rng.randint(1, 500) for _ in range(3))
        expr = f"({a} + {b}) * {c} - {a} % {b}"
        assert safe_eval(expr) == (a + b) * c - a % b
