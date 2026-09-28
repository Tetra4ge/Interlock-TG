from abc import ABC, abstractmethod
from server.llm.models import LLMRequest, LLMResponse

class BaseLLMProvider(ABC):
    @abstractmethod
    def generate(self, request: LLMRequest) -> LLMResponse:
        """Call the provider API and return a structured response."""
        pass
