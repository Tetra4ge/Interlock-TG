import hashlib
import json

from server.llm.cache import generate_cache_key
from server.llm.models import LLMMessage, LLMRequest, ToolCall, ToolSpec
from server.llm.providers.groq_provider import to_groq_messages


def _req(messages: list[LLMMessage], tools: list[ToolSpec] | None = None) -> LLMRequest:
    return LLMRequest(provider="groq", model="m", messages=messages, tools=tools or [])


def test_plain_requests_keep_their_pre_tool_cache_key() -> None:
    """Adding tool fields to LLMMessage must not orphan existing cached responses."""
    legacy = {
        "provider": "groq",
        "model": "m",
        "messages": [{"role": "system", "content": "s"}, {"role": "user", "content": "q"}],
        "tools": [],
        "temperature": 0.0,
        "max_tokens": 1000,
        "json_mode": False,
    }
    expected = hashlib.sha256(json.dumps(legacy, sort_keys=True).encode()).hexdigest()
    req = _req([LLMMessage(role="system", content="s"), LLMMessage(role="user", content="q")])
    assert generate_cache_key(req) == expected


def test_tool_turns_change_the_cache_key() -> None:
    base = [LLMMessage(role="user", content="q")]
    call = ToolCall(id="c1", name="find_entity", arguments={"name": "Tata"})
    with_call = [*base, LLMMessage(role="assistant", tool_calls=[call])]
    with_result = [*with_call, LLMMessage(role="tool", content="ok", tool_call_id="c1")]
    keys = {generate_cache_key(_req(m)) for m in (base, with_call, with_result)}
    assert len(keys) == 3


def test_a_different_tool_result_changes_the_key() -> None:
    def conv(result: str) -> LLMRequest:
        call = ToolCall(id="c1", name="t", arguments={})
        return _req(
            [
                LLMMessage(role="user", content="q"),
                LLMMessage(role="assistant", tool_calls=[call]),
                LLMMessage(role="tool", content=result, tool_call_id="c1"),
            ]
        )

    assert generate_cache_key(conv("a")) != generate_cache_key(conv("b"))


def test_groq_messages_replay_tool_calls_and_results() -> None:
    call = ToolCall(id="call_1", name="neighbors", arguments={"entity_id": "C:1", "hops": 1})
    out = to_groq_messages(
        [
            LLMMessage(role="system", content="sys"),
            LLMMessage(role="user", content="q"),
            LLMMessage(role="assistant", tool_calls=[call]),
            LLMMessage(role="tool", content="facts", tool_call_id="call_1"),
            LLMMessage(role="assistant", content="done"),
        ]
    )
    assert out[0] == {"role": "system", "content": "sys"}
    assert out[2]["role"] == "assistant" and out[2]["content"] == ""
    fn = out[2]["tool_calls"][0]
    assert fn["id"] == "call_1" and fn["type"] == "function"
    assert fn["function"]["name"] == "neighbors"
    assert json.loads(fn["function"]["arguments"]) == {"entity_id": "C:1", "hops": 1}
    assert out[3] == {"role": "tool", "tool_call_id": "call_1", "content": "facts"}
    assert out[4] == {"role": "assistant", "content": "done"}
    assert "tool_calls" not in out[4]
