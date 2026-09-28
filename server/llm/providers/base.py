from abc import ABC, abstractmethod

from server.llm.models import LLMRequest, LLMResponse


class RetryableError(Exception):
    """Rate limit, server error, timeout or connection failure. Safe to retry."""


class FatalError(Exception):
    """Auth failure or invalid request. Retrying will not help."""


class BaseLLMProvider(ABC):
    @abstractmethod
    def generate(self, request: LLMRequest) -> LLMResponse:
        """Call the provider API and return a structured response.

        Implementations should raise RetryableError for rate limits/5xx/timeouts
        and FatalError for auth/invalid-request failures, rather than swallowing
        them into LLMResponse.error, so the gateway can retry appropriately.
        """
