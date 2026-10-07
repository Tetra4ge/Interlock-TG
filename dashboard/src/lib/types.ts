// TypeScript mirrors of the API's Pydantic models (server/api/schemas.py and
// server/pipelines/models.py). Keep them in step: a backend change should surface here.

export type PipelineKey = "rag" | "graphrag" | "agent";

export const PIPELINE_KEYS: readonly PipelineKey[] = ["rag", "graphrag", "agent"];

export type Status = "ok" | "abstained" | "error" | "budget_exceeded";

export type AnswerType =
  | "entity"
  | "list"
  | "number"
  | "date"
  | "yes_no"
  | "text"
  | "not_found";

export interface Citation {
  doc_id: string;
  page: number;
  quote: string;
}

export interface EvidenceItem {
  kind: string; // "chunk" | "triple" | "tool_result" | "summary"
  ref_id: string;
  text: string;
}

export interface TraceStep {
  step: number;
  kind: string; // "retrieve" | "llm" | "tool" | "verify"
  name: string;
  input_summary: string;
  output_summary: string;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
  latency_ms: number;
  error: string | null;
}

export interface Usage {
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
  latency_ms: number;
  llm_calls: number;
  tool_calls: number;
}

export interface AnswerResult {
  pipeline: string;
  question: string;
  answer_short: string;
  answer_long: string;
  answer_type: AnswerType;
  citations: Citation[];
  evidence: EvidenceItem[];
  trace: TraceStep[];
  usage: Usage;
  status: Status;
}

export interface Health {
  tigergraph: boolean;
  turso: boolean;
  llm_key: boolean;
  demo_mode: boolean;
  llm_offline: boolean;
}

export interface CompareOut {
  request_id: string;
  results: Partial<Record<PipelineKey, AnswerResult>>;
  cached: boolean;
}

export interface ExampleQuestion {
  question: string;
  pipelines: string[];
}

export interface RunOut {
  run_id: string;
  pipeline: string;
  split: string;
  question_version: string;
  started_at: string | null;
  finished_at: string | null;
  git_commit: string | null;
  n_results: number;
  notes: string | null;
}

export interface MetricsBlock {
  n: number;
  correct_mean: number | null;
  correct_ci95: [number, number] | null;
  faithfulness_mean: number | null;
  citation_accuracy_mean: number | null;
  evidence_recall_mean: number | null;
  abstention_rate: number | null;
  error_count: number;
  failures: Record<string, number>;
  latency_median_ms: number | null;
  latency_p90_ms: number | null;
  cost_usd_mean: number | null;
  llm_calls_mean: number | null;
  tool_calls_mean: number | null;
  budget_exceeded_rate: number | null;
}

export interface RunMetrics {
  run_id: string;
  pipeline: string;
  split: string;
  question_version: string;
  git_commit: string | null;
  overall: MetricsBlock;
  by_category: Record<string, MetricsBlock>;
}

export interface ScoreRow {
  correct: number | null;
  faithfulness: number | null;
  citation_accuracy: number | null;
  evidence_recall: number | null;
  abstention_ok: number | null;
  failure_label: string | null;
  judge_reason: string | null;
}

export interface ResultOut {
  run_id: string;
  qid: string;
  question: string | null;
  category: string | null;
  result: AnswerResult;
  score: ScoreRow | null;
}

export interface QuestionOut {
  qid: string;
  version: string;
  question: string;
  category: string;
  answer_type: string;
  split: string;
  verified: boolean;
  gold_answer: unknown;
  gold_evidence: { doc_id: string; page: number }[] | null;
}

export interface PipelineCell {
  run_id: string;
  status: Status;
  answer_short: string;
  correct: number | null;
  failure_label: string | null;
  cost_usd: number;
  latency_ms: number;
  tool_calls: number;
}

export interface QuestionRow {
  qid: string;
  question: string;
  category: string;
  cells: Partial<Record<PipelineKey, PipelineCell>>;
}

export interface PairEntry {
  n: number;
  diff: number | null;
  ci95: [number, number] | null;
  verdict: string;
}

export interface PairResult {
  metric: string;
  a: PipelineKey;
  b: PipelineKey;
  overall: PairEntry;
  by_category: Record<string, PairEntry>;
}

export interface Leader {
  pipeline: PipelineKey | null;
  mean: number | null;
  runner_up: PipelineKey | null;
  tied: PipelineKey[];
  clear: boolean;
  reason: string;
}

export interface CompareRunsOut {
  runs: Partial<Record<PipelineKey, string>>;
  metrics: Partial<Record<PipelineKey, RunMetrics>>;
  questions: QuestionRow[];
  pairs: PairResult[];
  leaders: Record<string, Leader>;
}

export interface SubgraphNode {
  id: string;
  type: string;
  label: string;
}

export interface SubgraphEdge {
  id: string;
  type: string;
  source: string;
  target: string;
  label: string;
  fiscal_year: string;
  doc_id: string;
  page: number;
  quote: string;
}

export interface SubgraphOut {
  nodes: SubgraphNode[];
  edges: SubgraphEdge[];
  requested: number;
  found: number;
}

export interface DataQuality {
  documents: number;
  documents_parsed: number;
  documents_failed: number;
  companies: number;
  records_total: number;
  records_accepted: number;
  records_rejected: number;
  review_queue: number;
  entities_by_kind: Record<string, number>;
  mentions_by_method: Record<string, number>;
  provenance_complete_pct: number | null;
  note: string;
}

export interface ReviewItem {
  record_id: string;
  record_type: string;
  reason: string;
  created_at: string;
  company_id: string | null;
  fiscal_year: string | null;
  payload: Record<string, unknown>;
}

export interface DocumentPage {
  doc_id: string;
  page: number;
  text: string;
  company_id: string | null;
  fiscal_year: string | null;
  doc_type: string | null;
  pdf_available: boolean;
}

export type ApiResult<T> =
  | { ok: true; data: T }
  | { ok: false; error: string; status: number | null };
