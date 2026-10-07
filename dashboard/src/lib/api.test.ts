import { afterEach, describe, expect, it, vi } from "vitest";
import {
  API_URL,
  askQuestion,
  compareQuestion,
  errorMessage,
  fetchCompareRuns,
  fetchHealth,
  fetchMetrics,
  fetchQuestions,
  fetchSubgraph,
  request,
} from "./api";

function mockFetch(impl: (url: string, init?: RequestInit) => Promise<Response> | Response) {
  const fn = vi.fn(async (url: string, init?: RequestInit) => impl(url, init));
  vi.stubGlobal("fetch", fn);
  return fn;
}

const jsonResponse = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

afterEach(() => vi.unstubAllGlobals());

describe("request", () => {
  it("returns typed data on success", async () => {
    mockFetch(() =>
      jsonResponse({ tigergraph: true, turso: true, llm_key: false, demo_mode: true, llm_offline: false }),
    );
    const res = await fetchHealth();
    expect(res.ok).toBe(true);
    if (res.ok) expect(res.data.demo_mode).toBe(true);
  });

  it("surfaces the detail of an HTTP error", async () => {
    mockFetch(() => jsonResponse({ detail: "question must not be empty" }, 400));
    const res = await compareQuestion("");
    expect(res).toEqual({ ok: false, status: 400, error: "question must not be empty" });
  });

  it("passes a 503 'needs a key' message through for the UI to show", async () => {
    mockFetch(() => jsonResponse({ detail: "Live questions need an API key. Try an example." }, 503));
    const res = await compareQuestion("new question");
    expect(res.ok).toBe(false);
    if (!res.ok) expect(res.error).toContain("API key");
  });

  it("joins FastAPI validation errors", async () => {
    mockFetch(() =>
      jsonResponse({ detail: [{ msg: "Field required", loc: ["body", "question"] }, { msg: "bad" }] }, 422),
    );
    const res = await request("/x");
    expect(res.ok === false && res.error).toBe("Field required; bad");
  });

  it("explains a network failure instead of throwing", async () => {
    mockFetch(() => {
      throw new TypeError("fetch failed");
    });
    const res = await fetchHealth();
    expect(res.ok).toBe(false);
    if (!res.ok) {
      expect(res.status).toBeNull();
      expect(res.error).toContain(API_URL);
      expect(res.error).toContain("hl serve");
    }
  });

  it("copes with a non-JSON error body", async () => {
    mockFetch(() => new Response("<html>Bad Gateway</html>", { status: 502 }));
    const res = await request("/x");
    expect(res).toEqual({ ok: false, status: 502, error: "The API returned HTTP 502." });
  });

  it("treats an empty 200 as an error rather than returning null as data", async () => {
    mockFetch(() => new Response("", { status: 200 }));
    const res = await request("/x");
    expect(res.ok).toBe(false);
  });

  it("does not cache (dashboards must show the latest runs)", async () => {
    const fn = mockFetch(() => jsonResponse([]));
    await request("/runs");
    expect(fn.mock.calls[0][1]).toMatchObject({ cache: "no-store" });
  });
});

describe("errorMessage", () => {
  it("falls back to the status code for unknown shapes", () => {
    expect(errorMessage(null, 500)).toBe("The API returned HTTP 500.");
    expect(errorMessage({ detail: 5 }, 500)).toBe("The API returned HTTP 500.");
    expect(errorMessage({ detail: [] }, 422)).toBe("The API returned HTTP 422.");
  });
});

describe("endpoints", () => {
  it("encodes run ids in the path", async () => {
    const fn = mockFetch(() => jsonResponse({}));
    await fetchMetrics("run/with spaces?x");
    expect(fn.mock.calls[0][0]).toBe(`${API_URL}/runs/run%2Fwith%20spaces%3Fx/metrics`);
  });

  it("sends only the runs that were chosen", async () => {
    const fn = mockFetch(() => jsonResponse({}));
    await fetchCompareRuns({ rag: "r1", agent: "a1" });
    expect(fn.mock.calls[0][0]).toBe(`${API_URL}/compare-runs?rag=r1&agent=a1`);
  });

  it("builds the questions query", async () => {
    const fn = mockFetch(() => jsonResponse([]));
    await fetchQuestions("dev", true);
    await fetchQuestions();
    expect(fn.mock.calls[0][0]).toBe(`${API_URL}/questions?split=dev&include_gold=true`);
    expect(fn.mock.calls[1][0]).toBe(`${API_URL}/questions`);
  });

  it("joins edge ids for the subgraph route", async () => {
    const fn = mockFetch(() => jsonResponse({}));
    await fetchSubgraph(["a", "b-c"]);
    expect(fn.mock.calls[0][0]).toBe(`${API_URL}/graph/subgraph?edge_ids=a%2Cb-c`);
  });

  it("posts questions as JSON", async () => {
    const fn = mockFetch(() => jsonResponse({}));
    await compareQuestion("Who audits Tata Steel?");
    await askQuestion("q", "agent");
    expect(fn.mock.calls[0][1]).toMatchObject({ method: "POST" });
    expect(JSON.parse(String(fn.mock.calls[0][1]?.body))).toEqual({ question: "Who audits Tata Steel?" });
    expect(JSON.parse(String(fn.mock.calls[1][1]?.body))).toEqual({ question: "q", pipeline: "agent" });
  });
});
