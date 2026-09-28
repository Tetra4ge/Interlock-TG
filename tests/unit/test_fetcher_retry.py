import httpx
import pytest

from server.ingest.fetcher import PoliteClient


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    # Retry/backoff and the inter-request delay both call time.sleep; keep
    # tests fast without changing the retry logic under test.
    monkeypatch.setattr("server.ingest.fetcher.time.sleep", lambda *_a, **_k: None)


def _client(handler, delay: float = 0.0, max_retries: int = 3) -> PoliteClient:
    return PoliteClient(
        user_agent="test-agent",
        delay=delay,
        timeout=5.0,
        max_retries=max_retries,
        transport=httpx.MockTransport(handler),
    )


def test_retries_on_503_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503)
        return httpx.Response(200, content=b"%PDF-1.4 ok")

    client = _client(handler)
    response = client.get("https://example.com/report.pdf")

    assert response.status_code == 200
    assert calls["n"] == 3


def test_gives_up_after_max_retries() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503)

    client = _client(handler, max_retries=3)

    with pytest.raises(httpx.HTTPStatusError):
        client.get("https://example.com/report.pdf")

    assert calls["n"] == 3


def test_non_retryable_status_returns_immediately() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(404)

    client = _client(handler, max_retries=5)
    response = client.get("https://example.com/missing.pdf")

    assert response.status_code == 404
    assert calls["n"] == 1  # 404 isn't in RETRYABLE_STATUS, no retry


def test_delay_is_respected_between_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    # Real time.monotonic() (large, process-relative) makes the client's
    # initial `_last_request_at = 0.0` read as "long ago", so only the
    # second call should wait. Only time.sleep is faked, to keep the test fast.
    sleeps: list[float] = []
    monkeypatch.setattr("server.ingest.fetcher.time.sleep", lambda s: sleeps.append(s))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"ok")

    client = _client(handler, delay=3.0)
    client.get("https://example.com/a.pdf")  # first call: no prior request, no wait
    assert sleeps == []

    client.get("https://example.com/b.pdf")  # second call: must wait ~delay seconds

    assert len(sleeps) == 1
    assert sleeps[0] == pytest.approx(3.0, abs=0.1)
