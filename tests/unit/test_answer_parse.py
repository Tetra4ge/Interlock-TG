import pytest

from server.llm.models import LLMResponse
from server.pipelines.common import answer as answer_mod
from server.pipelines.common import tracer as tracer_mod
from server.pipelines.common.answer import final_answer
from server.pipelines.common.render import assign_labels
from server.pipelines.common.tracer import Tracer
from server.pipelines.models import EvidenceItem


class FakeConn:
    """Stands in for the Turso/libsql connection so the tracer never touches
    a real DB file (mirrors the FakeConn pattern in test_gateway.py)."""

    def execute(self, sql: str, params: list | None = None) -> None:
        return None

    def commit(self) -> None:
        pass

    def close(self) -> None:
        pass


@pytest.fixture(autouse=True)
def isolated_tracer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tracer_mod, "connect", lambda: FakeConn())


def _labels() -> dict:
    items = [
        EvidenceItem(kind="chunk", ref_id="c1", text="The auditor is Deloitte Haskins & Sells.")
    ]
    return assign_labels(items, {"c1": {"doc_id": "doc1", "page_start": 1, "page_end": 1}})


VALID_JSON = (
    '{"answer_type": "entity", "answer_short": "Deloitte Haskins & Sells", '
    '"answer_long": "The auditor is Deloitte Haskins & Sells [E1].", '
    '"citations": [{"evidence_id": "E1", "quote": "The auditor is Deloitte Haskins & Sells."}]}'
)
INVALID_JSON = '{"answer_type": "entity", "answer_short": "x"}'  # missing required fields


def _fake_call_llm(responses: list[LLMResponse]) -> callable:
    calls = {"n": 0}

    def _call(_req) -> LLMResponse:
        resp = responses[min(calls["n"], len(responses) - 1)]
        calls["n"] += 1
        return resp

    _call.calls = calls
    return _call


def test_valid_json_parsed_on_first_try(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _fake_call_llm(
        [LLMResponse(content=VALID_JSON, tokens_in=100, tokens_out=20, cost_usd=0.001)]
    )
    monkeypatch.setattr(answer_mod, "call_llm", fake)
    tr = Tracer("req1", "rag")

    ma, err = final_answer(tr, "Who audited the company?", _labels())

    assert err is None
    assert ma is not None
    assert ma.answer_short == "Deloitte Haskins & Sells"
    assert len(tr.steps) == 1
    assert tr.steps[0].name == "final_answer"


def test_invalid_json_then_valid_on_repair(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _fake_call_llm(
        [
            LLMResponse(content=INVALID_JSON, tokens_in=100, tokens_out=20),
            LLMResponse(content=VALID_JSON, tokens_in=100, tokens_out=20),
        ]
    )
    monkeypatch.setattr(answer_mod, "call_llm", fake)
    tr = Tracer("req2", "rag")

    ma, err = final_answer(tr, "Who audited the company?", _labels())

    assert err is None
    assert ma is not None
    assert ma.answer_short == "Deloitte Haskins & Sells"
    assert [s.name for s in tr.steps] == ["final_answer", "final_answer_repair"]


def test_invalid_json_twice_returns_error(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _fake_call_llm(
        [
            LLMResponse(content=INVALID_JSON, tokens_in=100, tokens_out=20),
            LLMResponse(content=INVALID_JSON, tokens_in=100, tokens_out=20),
        ]
    )
    monkeypatch.setattr(answer_mod, "call_llm", fake)
    tr = Tracer("req3", "rag")

    ma, err = final_answer(tr, "Who audited the company?", _labels())

    assert ma is None
    assert err is not None
    assert err.startswith("schema_invalid")


def test_llm_error_returns_error_without_repair(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _fake_call_llm(
        [LLMResponse(content="", tokens_in=0, tokens_out=0, error="rate_limited")]
    )
    monkeypatch.setattr(answer_mod, "call_llm", fake)
    tr = Tracer("req4", "rag")

    ma, err = final_answer(tr, "Who audited the company?", _labels())

    assert ma is None
    assert err == "llm_error: rate_limited"
    assert len(tr.steps) == 1
