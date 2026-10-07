"""Request/response models for the HTTP API that are not already in pipelines.models."""

from typing import Any

from pydantic import BaseModel, Field

from server.pipelines.models import AnswerResult

PIPELINE_NAMES = ("rag", "graphrag", "agent")


class AskIn(BaseModel):
    question: str
    pipeline: str


class CompareIn(BaseModel):
    question: str


class HealthOut(BaseModel):
    tigergraph: bool
    turso: bool
    llm_key: bool
    demo_mode: bool
    llm_offline: bool


class CompareOut(BaseModel):
    request_id: str
    results: dict[str, AnswerResult]
    cached: bool = False


class ExampleQuestion(BaseModel):
    question: str
    pipelines: list[str]  # pipelines that have a cached answer


class RunOut(BaseModel):
    run_id: str
    pipeline: str
    split: str
    question_version: str
    started_at: str | None = None
    finished_at: str | None = None
    git_commit: str | None = None
    n_results: int = 0
    notes: str | None = None


class MetricsBlock(BaseModel):
    n: int
    correct_mean: float | None = None
    correct_ci95: list[float] | None = None
    faithfulness_mean: float | None = None
    citation_accuracy_mean: float | None = None
    evidence_recall_mean: float | None = None
    abstention_rate: float | None = None
    error_count: int = 0
    failures: dict[str, int] = Field(default_factory=dict)
    latency_median_ms: float | None = None
    latency_p90_ms: float | None = None
    cost_usd_mean: float | None = None
    llm_calls_mean: float | None = None
    tool_calls_mean: float | None = None
    budget_exceeded_rate: float | None = None


class RunMetrics(BaseModel):
    run_id: str
    pipeline: str
    split: str
    question_version: str
    git_commit: str | None = None
    overall: MetricsBlock
    by_category: dict[str, MetricsBlock]


class ScoreRow(BaseModel):
    correct: float | None = None
    faithfulness: float | None = None
    citation_accuracy: float | None = None
    evidence_recall: float | None = None
    abstention_ok: int | None = None
    failure_label: str | None = None
    judge_reason: str | None = None


class ResultOut(BaseModel):
    run_id: str
    qid: str
    question: str | None = None
    category: str | None = None
    result: AnswerResult
    score: ScoreRow | None = None


class QuestionOut(BaseModel):
    qid: str
    version: str
    question: str
    category: str
    answer_type: str
    split: str
    verified: bool
    gold_answer: Any = None
    gold_evidence: list[dict[str, Any]] | None = None


class PipelineCell(BaseModel):
    """One pipeline's outcome on one question, for the joined comparison table."""

    run_id: str
    status: str
    answer_short: str
    correct: float | None = None
    failure_label: str | None = None
    cost_usd: float = 0.0
    latency_ms: int = 0
    tool_calls: int = 0


class QuestionRow(BaseModel):
    qid: str
    question: str
    category: str
    cells: dict[str, PipelineCell]


class PairEntry(BaseModel):
    n: int
    diff: float | None = None
    ci95: list[float] | None = None
    verdict: str


class PairResult(BaseModel):
    metric: str
    a: str
    b: str
    overall: PairEntry
    by_category: dict[str, PairEntry]


class Leader(BaseModel):
    """Who leads a category on mean accuracy, and whether the lead is clear."""

    pipeline: str | None
    mean: float | None
    runner_up: str | None = None
    tied: list[str] = Field(default_factory=list)  # pipelines sharing the top mean
    clear: bool = False
    reason: str = ""


class CompareRunsOut(BaseModel):
    runs: dict[str, str]  # pipeline key -> run_id
    metrics: dict[str, RunMetrics]
    questions: list[QuestionRow]
    pairs: list[PairResult]
    leaders: dict[str, Leader]


class SubgraphNode(BaseModel):
    id: str
    type: str
    label: str


class SubgraphEdge(BaseModel):
    id: str
    type: str
    source: str
    target: str
    label: str
    fiscal_year: str = ""
    doc_id: str = ""
    page: int = 0
    quote: str = ""


class SubgraphOut(BaseModel):
    nodes: list[SubgraphNode]
    edges: list[SubgraphEdge]
    requested: int
    found: int


class DataQualityOut(BaseModel):
    documents: int
    documents_parsed: int
    documents_failed: int
    companies: int
    records_total: int
    records_accepted: int
    records_rejected: int
    review_queue: int
    entities_by_kind: dict[str, int]
    mentions_by_method: dict[str, int]
    provenance_complete_pct: float | None
    note: str


class ReviewItem(BaseModel):
    record_id: str
    record_type: str
    reason: str
    created_at: str
    company_id: str | None = None
    fiscal_year: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class ErrorOut(BaseModel):
    detail: str
