from enum import StrEnum

from pydantic import BaseModel


class AnswerType(StrEnum):
    ENTITY = "entity"
    LIST = "list"
    NUMBER = "number"
    DATE = "date"
    YES_NO = "yes_no"
    TEXT = "text"
    NOT_FOUND = "not_found"


class Status(StrEnum):
    OK = "ok"
    ABSTAINED = "abstained"
    ERROR = "error"
    BUDGET = "budget_exceeded"


class Citation(BaseModel):
    doc_id: str
    page: int
    quote: str


class EvidenceItem(BaseModel):
    kind: str  # "chunk" | "triple" | "tool_result" | "summary"
    ref_id: str  # chunk_id, edge id, step id
    text: str


class TraceStep(BaseModel):
    step: int
    kind: str  # "retrieve" | "llm" | "tool" | "verify"
    name: str
    input_summary: str
    output_summary: str
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    error: str | None = None


class Usage(BaseModel):
    tokens_in: int
    tokens_out: int
    cost_usd: float
    latency_ms: int
    llm_calls: int
    tool_calls: int


class AnswerResult(BaseModel):
    pipeline: str  # "rag" | "graphrag" | "agent"
    question: str
    answer_short: str  # scored value, e.g. "Deloitte Haskins & Sells LLP"
    answer_long: str  # one-paragraph explanation with [doc, p.N] markers
    answer_type: AnswerType
    citations: list[Citation]
    evidence: list[EvidenceItem]
    trace: list[TraceStep]
    usage: Usage
    status: Status


class ModelCitation(BaseModel):
    """A citation as the LLM emits it: a label we gave it, never a raw doc/page."""

    evidence_id: str  # the label we assigned the evidence block, e.g. "E3"
    quote: str  # exact supporting text copied from that block


class ModelAnswer(BaseModel):
    """The LLM-facing output schema -- smaller than AnswerResult. The pipeline
    resolves each ModelCitation into a real Citation by looking up its label."""

    answer_type: AnswerType
    # the value only: name, "; "-joined list, number, date, yes/no, or "not found"
    answer_short: str
    answer_long: str  # 1 paragraph; cite with [E1], [E2]
    citations: list[ModelCitation]
