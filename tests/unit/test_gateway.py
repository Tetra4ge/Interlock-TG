from pathlib import Path

import pytest

from server.llm import cache, gateway
from server.llm.gateway import (
    OfflineCacheMiss,
    SpendCapExceeded,
    call_llm,
)
from server.llm.models import LLMMessage, LLMRequest, LLMResponse
from server.llm.providers.base import BaseLLMProvider, FatalError, RetryableError


class FakeProvider(BaseLLMProvider):
    """Mirrors the FakeProvider pattern from the phase-0 spec: fails
    `fail_times` times with `fail_with`, then succeeds."""

    def __init__(self, fail_times: int = 0, fail_with: type[Exception] = RetryableError) -> None:
        self.calls = 0
        self.fail_times = fail_times
        self.fail_with = fail_with

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.fail_with("simulated failure")
        return LLMResponse(content="OK", tokens_in=10, tokens_out=2, latency_ms=5)


class ExplodingProvider(BaseLLMProvider):
    """A provider that must never be invoked (used to prove cache hits skip it)."""

    def generate(self, request: LLMRequest) -> LLMResponse:
        raise AssertionError("provider should not be called on a cache hit")


class FakeCursor:
    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows

    def fetchall(self) -> list[tuple]:
        return self._rows


class FakeConn:
    """Stands in for the Turso/libsql connection so gateway tests never
    touch a real database file."""

    def __init__(self, spent_so_far: float = 0.0) -> None:
        self.spent_so_far = spent_so_far
        self.inserts: list[tuple] = []

    def execute(self, sql: str, params: list | None = None) -> FakeCursor:
        if sql.strip().upper().startswith("SELECT"):
            return FakeCursor([(self.spent_so_far,)])
        self.inserts.append((sql, params))
        return FakeCursor([])

    def commit(self) -> None:
        pass

    def close(self) -> None:
        pass


def _request(**overrides: object) -> LLMRequest:
    defaults: dict = {
        "provider": "fake",
        "model": "fake-model",
        "messages": [LLMMessage(role="user", content="hello")],
    }
    defaults.update(overrides)
    return LLMRequest(**defaults)


@pytest.fixture(autouse=True)
def isolated_gateway(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(gateway, "connect", lambda: FakeConn())
    monkeypatch.setattr(gateway, "_spent_usd", None)  # reset the module-level spend cache
    monkeypatch.setattr(gateway.settings, "llm_offline", False)
    monkeypatch.setattr(gateway.settings, "llm_spend_cap_usd", 25.0)
    monkeypatch.setattr(gateway, "BASE_DELAY_SECONDS", 0.0)
    monkeypatch.setattr(gateway.time, "sleep", lambda *_args, **_kwargs: None)


def test_cache_hit_never_calls_the_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    request = _request()
    monkeypatch.setitem(gateway.PROVIDERS, "fake", ExplodingProvider)  # would raise if invoked
    cache.put_cached(
        cache.generate_cache_key(request),
        LLMResponse(content="cached", tokens_in=1, tokens_out=1, latency_ms=1),
    )

    response = call_llm(request)

    assert response.cache_hit is True
    assert response.cost_usd == 0.0
    assert response.content == "cached"


def test_retries_on_retryable_error_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = FakeProvider(fail_times=2, fail_with=RetryableError)
    monkeypatch.setitem(gateway.PROVIDERS, "fake", lambda: provider)

    response = call_llm(_request())

    assert response.content == "OK"
    assert provider.calls == 3


def test_gives_up_after_max_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = FakeProvider(fail_times=gateway.MAX_RETRIES + 1, fail_with=RetryableError)
    monkeypatch.setitem(gateway.PROVIDERS, "fake", lambda: provider)

    with pytest.raises(RetryableError):
        call_llm(_request())

    assert provider.calls == gateway.MAX_RETRIES


def test_fatal_error_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = FakeProvider(fail_times=1, fail_with=FatalError)
    monkeypatch.setitem(gateway.PROVIDERS, "fake", lambda: provider)

    with pytest.raises(FatalError):
        call_llm(_request())

    assert provider.calls == 1


def test_spend_cap_raises_before_calling_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gateway.settings, "llm_spend_cap_usd", 0.0)
    monkeypatch.setitem(gateway.PROVIDERS, "fake", ExplodingProvider)

    with pytest.raises(SpendCapExceeded):
        call_llm(_request())


def test_offline_mode_raises_on_cache_miss(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gateway.settings, "llm_offline", True)
    monkeypatch.setitem(gateway.PROVIDERS, "fake", ExplodingProvider)

    with pytest.raises(OfflineCacheMiss):
        call_llm(_request())
