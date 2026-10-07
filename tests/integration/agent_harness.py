"""Shared fixture for the agent integration tests.

No live TigerGraph or LLM exists here, so the graph runner, entity index, vector
search and the three LLM roles (agent turns, final answer, verifier) are scripted.
Everything between those seams is the real code: tools, guardrails, evidence log,
loop, budgets, shared final answer, citation validation and verifier."""

import json
from typing import Any

from server.llm.models import LLMResponse, ToolCall
from tests.unit.graphrag_fixtures import director, raw_result, txn_edges

STEEL_DOC, MOTORS_DOC = "a" * 24, "b" * 24
NAMES = {
    "C:TATASTEEL": ("Tata Steel Limited", "company"),
    "C:TATAMOTORS": ("Tata Motors Limited", "company"),
    "P:1": ("Anil Kumar Sharma", "person"),
    "P:2": ("Rajesh Verma", "person"),
}


class FakeConn:
    def execute(self, sql: str, params: list | None = None) -> None:
        return None

    def commit(self) -> None:
        pass

    def close(self) -> None:
        pass


def tool_turn(*calls: tuple[str, dict], text: str = "") -> LLMResponse:
    tool_calls = [
        ToolCall(id=f"call-{i}-{n}", name=n, arguments=a) for i, (n, a) in enumerate(calls)
    ]
    return LLMResponse(content=text, tool_calls=tool_calls, tokens_in=400, tokens_out=40)


def stop_turn(text: str = "Ready: E1") -> LLMResponse:
    return LLMResponse(content=text, tokens_in=400, tokens_out=10)


def answer_json(
    short: str, long: str, citations: list[tuple[str, str]], typ: str = "entity"
) -> str:
    return json.dumps(
        {
            "answer_type": typ,
            "answer_short": short,
            "answer_long": long,
            "citations": [{"evidence_id": e, "quote": q} for e, q in citations],
        }
    )


def verdict_json(*claims: tuple[str, str, list[str]]) -> str:
    return json.dumps(
        {"claims": [{"claim": c, "verdict": v, "evidence_labels": e} for c, v, e in claims]}
    )


class ScriptedLLM:
    """Routes each request to the right script: tool-bearing requests are agent
    turns, prompts starting 'Check the draft answer' are the verifier, anything
    else is the shared final answer."""

    def __init__(self) -> None:
        self.agent: list[Any] = []
        self.final: list[str] = []
        self.verifier: list[str] = []
        self.requests: dict[str, list] = {"agent": [], "final": [], "verifier": []}

    def __call__(self, req):  # type: ignore[no-untyped-def]
        last = req.messages[-1].content
        if req.tools:
            role, script = "agent", self.agent
        elif last.startswith("Check the draft answer"):
            role, script = "verifier", self.verifier
        else:
            role, script = "final", self.final
        self.requests[role].append(req.model_copy(deep=True))
        if not script:
            raise AssertionError(f"unscripted {role} call #{len(self.requests[role])}")
        out = script.pop(0)
        if isinstance(out, Exception):
            raise out
        if isinstance(out, LLMResponse):
            return out
        return LLMResponse(content=out, tokens_in=500, tokens_out=60, cost_usd=0.0)


class Graph:
    def __init__(self, *expand_responses: Any) -> None:
        self.responses = list(expand_responses)
        self.expand_calls: list[dict] = []
        self.query_calls: list[tuple] = []

    def expand(self, name: str, params: dict, timeout_s: int | None = None) -> Any:
        self.expand_calls.append(params)
        out = self.responses.pop(0)
        if isinstance(out, Exception):
            raise out
        return out

    def query(self, name: str, params: dict, timeout_s: int | None = None) -> Any:
        self.query_calls.append((name, params))
        return [
            {
                "Shared": [
                    {"v_id": "P:1", "v_type": "Person", "attributes": {"name": "Anil Kumar Sharma"}}
                ]
            }
        ]


STEEL_FY24 = raw_result(
    [
        director("P:1", "C:TATASTEEL", "FY2023-24", "d-steel-24", doc_id=STEEL_DOC, page=46,
                 quote="Anil Kumar Sharma | Independent Director"),
    ]
)  # fmt: skip
STEEL_FY23 = raw_result(
    [
        director("P:2", "C:TATASTEEL", "FY2022-23", "d-steel-23", doc_id=STEEL_DOC, page=41,
                 quote="Rajesh Verma | Independent Director"),
    ]
)  # fmt: skip
TXN = raw_result(
    txn_edges("T1", "C:TATASTEEL", "C:TATAMOTORS", "t1"),
    {"T1": {"nature": "Sale of goods", "amount_inr": 482000000.0, "fiscal_year": "FY2022-23"}},
)
