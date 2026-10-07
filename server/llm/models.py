from pydantic import BaseModel


class ToolSpec(BaseModel):
    name: str
    description: str
    parameters: dict  # JSON Schema


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict


class LLMMessage(BaseModel):
    """role is system | user | assistant | tool. An assistant turn that called
    tools carries `tool_calls`; each answering `tool` message carries the
    `tool_call_id` it responds to."""

    role: str
    content: str = ""
    tool_calls: list[ToolCall] = []
    tool_call_id: str | None = None


class LLMRequest(BaseModel):
    provider: str
    model: str
    messages: list[LLMMessage]
    tools: list[ToolSpec] = []
    temperature: float = 0.0
    max_tokens: int = 1000
    json_mode: bool = False


class LLMResponse(BaseModel):
    content: str
    tool_calls: list[ToolCall] = []
    tokens_in: int
    tokens_out: int
    cost_usd: float = 0.0
    latency_ms: int = 0
    cache_hit: bool = False
    error: str | None = None
