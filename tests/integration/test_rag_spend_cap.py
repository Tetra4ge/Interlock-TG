import pytest

from server.llm.gateway import SpendCapExceeded
from server.pipelines.common import tracer as tracer_mod
from server.pipelines.models import Status
from server.pipelines.rag import RAGPipeline


class _FakeConn:
    def execute(self, *_args: object, **_kwargs: object) -> None:
        return None

    def commit(self) -> None:
        return None

    def close(self) -> None:
        return None


@pytest.fixture
def isolated_tracer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tracer_mod, "connect", lambda: _FakeConn())
    monkeypatch.setattr("server.pipelines.rag._excluded_doc_ids", lambda: set())


def test_spend_cap_yields_error_with_spend_cap_reason(
    monkeypatch: pytest.MonkeyPatch, isolated_tracer: None
) -> None:
    def raise_cap(*_args: object, **_kwargs: object) -> None:
        raise SpendCapExceeded("spent $5.00")

    monkeypatch.setattr("server.pipelines.rag.vector_search", raise_cap)

    result = RAGPipeline().answer("any question", "req-cap")

    assert result.status == Status.ERROR
    assert result.trace[-1].error == "spend_cap"
