import type {
  AnswerResult,
  ApiResult,
  CompareOut,
  CompareRunsOut,
  DataQuality,
  ExampleQuestion,
  Health,
  PipelineKey,
  QuestionOut,
  ResultOut,
  ReviewItem,
  RunMetrics,
  RunOut,
  SubgraphOut,
} from "./types";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(
  /\/+$/,
  "",
);

/** Pull a human message out of an error response: FastAPI sends {"detail": "..."} for
 *  HTTP errors and {"detail": [{msg, loc}, ...]} for validation errors. */
export function errorMessage(body: unknown, status: number): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      const msgs = detail
        .map((d) => (d && typeof d === "object" && "msg" in d ? String((d as { msg: unknown }).msg) : ""))
        .filter(Boolean);
      if (msgs.length) return msgs.join("; ");
    }
  }
  return `The API returned HTTP ${status}.`;
}

/** Every call returns an ApiResult and never throws, so a page can render an error
 *  panel instead of crashing when the API is down or rejects the request. */
export async function request<T>(path: string, init?: RequestInit): Promise<ApiResult<T>> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { cache: "no-store", ...init });
  } catch {
    return {
      ok: false,
      status: null,
      error: `Cannot reach the API at ${API_URL}. Start it with "uv run hl serve".`,
    };
  }

  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    // an empty or non-JSON body is handled below
  }
  if (!res.ok) return { ok: false, status: res.status, error: errorMessage(body, res.status) };
  if (body === null) {
    return { ok: false, status: res.status, error: "The API returned an empty response." };
  }
  return { ok: true, data: body as T };
}

function query(params: Record<string, string | boolean | null | undefined>): string {
  const usp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "" && v !== false) usp.set(k, String(v));
  }
  const s = usp.toString();
  return s ? `?${s}` : "";
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const fetchHealth = () => request<Health>("/health");
export const fetchRuns = () => request<RunOut[]>("/runs");
export const fetchMetrics = (runId: string) =>
  request<RunMetrics>(`/runs/${encodeURIComponent(runId)}/metrics`);
export const fetchResult = (runId: string, qid: string) =>
  request<ResultOut>(`/runs/${encodeURIComponent(runId)}/results/${encodeURIComponent(qid)}`);
export const fetchCompareRuns = (runs: Partial<Record<PipelineKey, string>>) =>
  request<CompareRunsOut>(`/compare-runs${query(runs)}`);
export const fetchQuestions = (split?: "dev" | "test", includeGold = false) =>
  request<QuestionOut[]>(`/questions${query({ split, include_gold: includeGold })}`);
export const fetchSubgraph = (edgeIds: string[]) =>
  request<SubgraphOut>(`/graph/subgraph${query({ edge_ids: edgeIds.join(",") })}`);
export const fetchDataQuality = () => request<DataQuality>("/data-quality");
export const fetchExamples = () => request<ExampleQuestion[]>("/examples");
export const fetchReviewQueue = () => request<ReviewItem[]>("/review-queue");
export const compareQuestion = (question: string) =>
  request<CompareOut>("/compare", json({ question }));
export const askQuestion = (question: string, pipeline: PipelineKey) =>
  request<AnswerResult>("/ask", json({ question, pipeline }));
