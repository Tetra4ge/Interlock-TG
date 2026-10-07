import json
import time
from typing import Any

import groq
from groq import Groq

from server.llm.models import LLMRequest, LLMResponse, ToolCall
from server.llm.providers.base import BaseLLMProvider, FatalError, RetryableError
from server.settings import settings

# Errors worth retrying with backoff: rate limits, transient server/connection issues.
_RETRYABLE = (
    groq.RateLimitError,
    groq.InternalServerError,
    groq.APIConnectionError,
    groq.APITimeoutError,
)
# Errors that will never succeed on retry: bad credentials or a malformed request.
_FATAL = (
    groq.AuthenticationError,
    groq.PermissionDeniedError,
    groq.BadRequestError,
    groq.NotFoundError,
)


def _to_groq_tools(tools: list) -> list[dict] | None:
    if not tools:
        return None
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in tools
    ]


def to_groq_messages(messages: list) -> list[dict[str, Any]]:
    """Chat messages in Groq's (OpenAI-compatible) shape. An assistant turn that
    made tool calls must be replayed with them, and each tool result must name
    the call it answers, or the next request is rejected."""
    out: list[dict[str, Any]] = []
    for m in messages:
        if m.role == "assistant" and m.tool_calls:
            out.append(
                {
                    "role": "assistant",
                    "content": m.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                        }
                        for tc in m.tool_calls
                    ],
                }
            )
        elif m.role == "tool":
            out.append({"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content})
        else:
            out.append({"role": m.role, "content": m.content})
    return out


class GroqProvider(BaseLLMProvider):
    def __init__(self) -> None:
        self.client = Groq(api_key=settings.groq_api_key)

    def generate(self, request: LLMRequest) -> LLMResponse:
        start_time = time.perf_counter()

        kwargs: dict[str, Any] = {
            "model": request.model,
            "messages": to_groq_messages(request.messages),
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        if request.json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        groq_tools = _to_groq_tools(request.tools)
        if groq_tools:
            kwargs["tools"] = groq_tools

        try:
            res = self.client.chat.completions.create(**kwargs)
        except _FATAL as e:
            raise FatalError(str(e)) from e
        except _RETRYABLE as e:
            raise RetryableError(str(e)) from e

        latency = int((time.perf_counter() - start_time) * 1000)

        message = res.choices[0].message
        content = message.content or ""
        tokens_in = res.usage.prompt_tokens if res.usage else 0
        tokens_out = res.usage.completion_tokens if res.usage else 0

        tool_calls = [
            ToolCall(
                id=tc.id,
                name=tc.function.name,
                arguments=json.loads(tc.function.arguments or "{}"),
            )
            for tc in (message.tool_calls or [])
        ]

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency,
        )
