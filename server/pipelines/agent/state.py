import time
from typing import Any

from pydantic import BaseModel, Field

from server.llm.models import LLMMessage
from server.pipelines.config import AGENT, AgentConfig

RUNNING = "running"
ANSWERED = "answered"
BUDGET_EXCEEDED = "budget_exceeded"
ERROR = "error"


class Budget(BaseModel):
    max_steps: int = 8
    max_tokens: int = 40_000
    timeout_s: int = 120

    @classmethod
    def from_config(cls, cfg: AgentConfig = AGENT) -> "Budget":
        return cls(
            max_steps=cfg.max_steps, max_tokens=cfg.max_tokens, timeout_s=cfg.timeout_seconds
        )


class Step(BaseModel):
    n: int
    tool: str
    args: dict[str, Any]
    ok: bool
    result_labels: list[str] = Field(
        default_factory=list
    )  # evidence this step created, e.g. ["E4"]
    summary: str = ""
    latency_ms: int = 0


class AgentState(BaseModel):
    question: str
    messages: list[LLMMessage] = Field(default_factory=list)
    steps: list[Step] = Field(default_factory=list)
    tokens_used: int = 0
    started: float = Field(default_factory=time.perf_counter)
    status: str = RUNNING
    stop_reason: str | None = None
    repeat_counter: dict[str, int] = Field(default_factory=dict)  # "tool:args" -> times called
    graph_query_failures: int = 0
    last_text: str = ""  # the model's last free-text message (may name [E#] it relied on)

    def elapsed_s(self) -> float:
        return time.perf_counter() - self.started

    def check_budget(self, budget: Budget) -> str | None:
        """The reason a budget is spent, or None. Spending a budget is a normal,
        recorded outcome, not an error."""
        if len(self.steps) >= budget.max_steps:
            return "max_steps"
        if self.tokens_used >= budget.max_tokens:
            return "max_tokens"
        if self.elapsed_s() > budget.timeout_s:
            return "timeout"
        return None
