from pathlib import Path

import pytest

from server.llm import cache
from server.llm.cache import generate_cache_key, get_cached, put_cached
from server.llm.models import LLMMessage, LLMRequest, LLMResponse


@pytest.fixture(autouse=True)
def isolated_cache_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the cache to a throwaway directory so tests never touch
    the real data/cache/llm/ or leak state between tests."""
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    return tmp_path


def _request(**overrides: object) -> LLMRequest:
    defaults: dict = {
        "provider": "groq",
        "model": "llama-3.1-8b-instant",
        "messages": [LLMMessage(role="user", content="hello")],
        "temperature": 0.0,
    }
    defaults.update(overrides)
    return LLMRequest(**defaults)


def test_cache_key_is_deterministic_for_identical_requests() -> None:
    key_a = generate_cache_key(_request())
    key_b = generate_cache_key(_request())
    assert key_a == key_b


def test_cache_key_stable_regardless_of_message_construction_order() -> None:
    # Build the "same" request via differently-ordered kwargs/dict construction;
    # sort_keys=True in the hash must make this irrelevant.
    req_a = LLMRequest(provider="groq", model="m", messages=[LLMMessage(role="user", content="hi")])
    req_b = LLMRequest(messages=[LLMMessage(content="hi", role="user")], model="m", provider="groq")
    assert generate_cache_key(req_a) == generate_cache_key(req_b)


def test_cache_key_changes_when_temperature_changes() -> None:
    key_a = generate_cache_key(_request(temperature=0.0))
    key_b = generate_cache_key(_request(temperature=0.7))
    assert key_a != key_b


def test_cache_key_changes_when_model_changes() -> None:
    key_a = generate_cache_key(_request(model="llama-3.1-8b-instant"))
    key_b = generate_cache_key(_request(model="llama-3.1-70b-versatile"))
    assert key_a != key_b


def test_cache_key_changes_when_messages_change() -> None:
    key_a = generate_cache_key(_request())
    key_b = generate_cache_key(
        _request(messages=[LLMMessage(role="user", content="a different question")])
    )
    assert key_a != key_b


def test_get_cached_returns_none_when_missing() -> None:
    assert get_cached("does-not-exist") is None


def test_put_then_get_round_trip() -> None:
    response = LLMResponse(content="hello world", tokens_in=5, tokens_out=3, latency_ms=42)
    put_cached("some-key", response)

    loaded = get_cached("some-key")

    assert loaded is not None
    assert loaded.content == "hello world"
    assert loaded.tokens_in == 5
    assert loaded.tokens_out == 3


def test_put_cached_write_is_atomic_and_leaves_no_tmp_file(isolated_cache_dir: Path) -> None:
    response = LLMResponse(content="ok", tokens_in=1, tokens_out=1, latency_ms=1)
    put_cached("atomic-key", response)

    files = list(isolated_cache_dir.iterdir())
    assert [f.name for f in files] == ["atomic-key.json"]
    assert not any(f.suffix == ".tmp" for f in files)
