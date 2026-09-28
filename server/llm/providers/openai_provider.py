import time
from openai import OpenAI
from server.settings import settings
from server.llm.models import LLMRequest, LLMResponse
from server.llm.providers.base import BaseLLMProvider

class OpenAIProvider(BaseLLMProvider):
    def __init__(self):
        self.client = OpenAI(api_key=settings.openai_api_key)
        
    def generate(self, request: LLMRequest) -> LLMResponse:
        start_time = time.perf_counter()
        
        # Prepare kwargs
        kwargs = {
            "model": request.model,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        if request.json_mode:
            kwargs["response_format"] = {"type": "json_object"}
            
        try:
            # Sync call
            res = self.client.chat.completions.create(**kwargs)
            latency = int((time.perf_counter() - start_time) * 1000)
            
            content = res.choices[0].message.content or ""
            tokens_in = res.usage.prompt_tokens if res.usage else 0
            tokens_out = res.usage.completion_tokens if res.usage else 0
            
            return LLMResponse(
                content=content,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                latency_ms=latency
            )
        except Exception as e:
            latency = int((time.perf_counter() - start_time) * 1000)
            return LLMResponse(
                content="", tokens_in=0, tokens_out=0, latency_ms=latency, error=str(e)
            )
