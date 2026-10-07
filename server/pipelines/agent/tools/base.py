import re
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field

from server.parse.tokens import estimate_tokens
from server.pipelines.agent.evidence_log import EvidenceLog
from server.pipelines.common.tracer import Tracer
from server.pipelines.config import AGENT, AgentConfig

CHARS_PER_TOKEN = 4
ENTITY_ID_RE = re.compile(r"[CPA]:[A-Za-z0-9_\-|]{1,62}")


class ToolResult(BaseModel):
    ok: bool
    text: str
    labels: list[str] = Field(default_factory=list)  # evidence labels this call created or used
    latency_ms: int = 0


class ToolContext:
    def __init__(
        self, question: str, log: EvidenceLog, tracer: Tracer, cfg: AgentConfig = AGENT
    ) -> None:
        self.question = question
        self.log = log
        self.tracer = tracer
        self.cfg = cfg


class ToolDef(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    name: str
    description: str
    args_model: type[BaseModel]
    run: Callable[[ToolContext, Any], ToolResult]


def error(message: str) -> ToolResult:
    return ToolResult(ok=False, text=f"error: {message}")


def cap_text(text: str, max_tokens: int) -> str:
    """Tool output is replayed in every later turn, so an uncapped result makes
    cost grow quadratically with steps."""
    if estimate_tokens(text) <= max_tokens:
        return text
    cut = text[: max_tokens * CHARS_PER_TOKEN].rstrip()
    return f"{cut}\n... [output truncated to fit the tool output limit]"


def check_entity_id(entity_id: str) -> str | None:
    """None if usable, else the message to show the model."""
    if not ENTITY_ID_RE.fullmatch(entity_id):
        return (
            f"{entity_id!r} is not an entity_id. Use find_entity to get ids "
            "(they look like C:TATASTEEL, P:x1a2b3c or A:x4d5e6f)."
        )
    return None
