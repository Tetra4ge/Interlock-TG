import pytest

from server.pipelines.common import tracer as tracer_mod
from server.pipelines.common.tracer import Tracer


class _FakeConn:
    def execute(self, *_a: object) -> None:
        return None

    def commit(self) -> None:
        pass

    def close(self) -> None:
        pass


@pytest.fixture(autouse=True)
def _no_db(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tracer_mod, "connect", lambda: _FakeConn())


def test_only_llm_steps_count_as_llm_calls() -> None:
    # A RAG turn: retrieve + one LLM call + a local citation check.
    tr = Tracer("req", "rag")
    tr.add("retrieve", "vector_search", "", "")
    tr.add("llm", "final_answer", "", "", tokens_in=100, tokens_out=20)
    tr.add("verify", "validate_citations", "", "")

    usage = tr.usage(total_latency_ms=10)
    # verify is a local check, not an LLM call.
    assert usage.llm_calls == 1
    assert usage.tool_calls == 0


def test_repair_counts_as_a_second_llm_call() -> None:
    tr = Tracer("req", "rag")
    tr.add("llm", "final_answer", "", "")
    tr.add("llm", "final_answer_repair", "", "")
    tr.add("verify", "validate_citations", "", "")
    assert tr.usage(1).llm_calls == 2


def test_a_verify_step_that_spent_tokens_is_an_llm_call() -> None:
    tr = Tracer("req", "agent")
    tr.add("llm", "final_answer", "", "", tokens_in=100, tokens_out=20)
    tr.add("verify", "verifier", "", "", tokens_in=300, tokens_out=40, cost_usd=0.002)
    tr.add("verify", "validate_citations", "", "")

    usage = tr.usage(total_latency_ms=10)

    assert usage.llm_calls == 2
    assert usage.tokens_in == 400 and usage.cost_usd == 0.002
