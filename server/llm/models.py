from typing import List, Optional
from pydantic import BaseModel

class LLMMessage(BaseModel):
    role: str
    content: str

class LLMRequest(BaseModel):
    provider: str
    model: str
    messages: List[LLMMessage]
    temperature: float = 0.0
    max_tokens: int = 1000
    json_mode: bool = False

class LLMResponse(BaseModel):
    content: str
    tokens_in: int
    tokens_out: int
    cost_usd: float = 0.0
    latency_ms: int = 0
    cache_hit: bool = False
    error: Optional[str] = None
