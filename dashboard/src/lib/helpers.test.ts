import { describe, expect, it } from "vitest";
import { accuracyRows, allZero, callsRows, failureStack, takeaways, tradeoffPoints } from "./chart";
import { citationChips, edgeIdsOf, goldEdgeIds, splitMarkers } from "./evidence";
import { humanize, money, ms, pct, pctRange, shortId, signed } from "./format";
import { PIPELINES, PIPELINE_ORDER, isPipelineKey } from "./pipelines";
import { defaultSelection, sampleCaveats, selectionFromParams, selectionQuery } from "./runs";
import type { AnswerResult, CompareRunsOut, MetricsBlock, RunOut, SubgraphEdge } from "./types";

const block = (over: Partial<MetricsBlock> = {}): MetricsBlock => ({
  n: 10, correct_mean: 0.5, correct_ci95: [0.3, 0.8], faithfulness_mean: null,
  citation_accuracy_mean: null, evidence_recall_mean: null, abstention_rate: null, error_count: 0,
  failures: {}, latency_median_ms: 2000, latency_p90_ms: 3000, cost_usd_mean: 0.01,
  llm_calls_mean: 1, tool_calls_mean: 0, budget_exceeded_rate: 0, ...over,
});

const run = (run_id: string, pipeline: string, split = "dev", n = 5): RunOut => ({
  run_id, pipeline, split, question_version: "v1", started_at: null, finished_at: null,
  git_commit: null, n_results: n, notes: null,
});

describe("format", () => {
  it("formats percentages and ranges, with a dash for missing values", () => {
    expect(pct(0.756)).toBe("76%");
    expect(pct(0.756, 1)).toBe("75.6%");
    expect(pct(null)).toBe("–");
    expect(pctRange([0.3, 0.8])).toBe("30%–80%");
    expect(pctRange(null)).toBe("–");
  });
  it("formats money, latency and signed deltas", () => {
    expect(money(0)).toBe("$0");
    expect(money(0.0042)).toBe("$0.0042");
    expect(money(0.1234)).toBe("$0.123");
    expect(ms(850)).toBe("850 ms");
    expect(ms(57000)).toBe("57.0 s");
    expect(signed(0.5)).toBe("+0.50");
    expect(signed(-0.25)).toBe("-0.25");
    expect(signed(null)).toBe("–");
  });
  it("humanizes labels and shortens ids", () => {
    expect(humanize("retrieval_miss")).toBe("Retrieval miss");
    expect(humanize("")).toBe("");
    expect(shortId("a".repeat(30))).toBe(`${"a".repeat(12)}…`);
    expect(shortId("short")).toBe("short");
  });
});

describe("pipelines", () => {
  it("uses the colourblind-friendly palette from the plan", () => {
    expect(PIPELINES.rag.color).toBe("#3B82F6");
    expect(PIPELINES.graphrag.color).toBe("#10B981");
    expect(PIPELINES.agent.color).toBe("#8B5CF6");
    expect(PIPELINE_ORDER).toEqual(["rag", "graphrag", "agent"]);
  });
  it("recognises pipeline keys", () => {
    expect(isPipelineKey("agent")).toBe(true);
    expect(isPipelineKey("magic")).toBe(false);
  });
});

describe("run selection", () => {
  const runs = [
    run("rag-test", "rag", "test"),
    run("rag-dev", "rag", "dev"),
    run("agent-dev", "agent", "dev"),
    run("empty", "graphrag", "dev", 0),
  ];

  it("defaults to the newest run per pipeline, preferring the split", () => {
    expect(defaultSelection(runs, "dev")).toEqual({ rag: "rag-dev", agent: "agent-dev" });
    expect(defaultSelection(runs, "test")).toEqual({ rag: "rag-test", agent: "agent-dev" });
    expect(defaultSelection(runs)).toEqual({ rag: "rag-test", agent: "agent-dev" });
  });
  it("skips runs with no results", () => {
    expect(defaultSelection(runs).graphrag).toBeUndefined();
  });
  it("respects an explicit URL choice exactly", () => {
    expect(selectionFromParams({ rag: "rag-test" }, runs, "dev")).toEqual({ rag: "rag-test" });
  });
  it("ignores unknown or mismatched run ids and falls back to defaults", () => {
    expect(selectionFromParams({ rag: "nope" }, runs, "dev")).toEqual({ rag: "rag-dev", agent: "agent-dev" });
    expect(selectionFromParams({ agent: "rag-dev" }, runs, "dev")).toEqual({ rag: "rag-dev", agent: "agent-dev" });
  });
  it("accepts array-valued params", () => {
    expect(selectionFromParams({ rag: ["rag-test", "x"] }, runs)).toEqual({ rag: "rag-test" });
  });
  it("round-trips through a query string", () => {
    expect(selectionQuery({ rag: "a", agent: "b" })).toBe("?rag=a&agent=b");
    expect(selectionQuery({})).toBe("");
  });
});

describe("chart data", () => {
  const metrics: CompareRunsOut["metrics"] = {
    rag: {
      run_id: "r", pipeline: "rag", split: "dev", question_version: "v1", git_commit: null,
      overall: block({ correct_mean: 0.4, correct_ci95: [0.2, 0.7], failures: { retrieval_miss: 3 } }),
      by_category: { single_fact: block({ correct_mean: 0.5 }) },
    },
    agent: {
      run_id: "a", pipeline: "agent", split: "dev", question_version: "v1", git_commit: null,
      overall: block({ correct_mean: 0.9, correct_ci95: null, tool_calls_mean: 3.4, llm_calls_mean: 5.4, failures: { budget_loop: 1 } }),
      by_category: { single_fact: block({ correct_mean: 0.9 }), multi_hop: block({ n: 4, correct_mean: 0.8 }) },
    },
  };

  it("builds grouped rows with error-bar offsets", () => {
    const rows = accuracyRows(metrics);
    expect(rows.map((r) => r.category)).toEqual(["overall", "multi_hop", "single_fact"]);
    const overall = rows[0];
    expect(overall.rag).toBe(0.4);
    const [lo, hi] = overall.rag_err as [number, number];
    expect(lo).toBeCloseTo(0.2);
    expect(hi).toBeCloseTo(0.3);
    expect(overall.agent_err).toBeNull(); // no interval available
  });
  it("leaves a pipeline's value null where it has no questions", () => {
    const multi = accuracyRows(metrics).find((r) => r.category === "multi_hop")!;
    expect(multi.rag).toBeNull();
    expect(multi.agent).toBe(0.8);
  });
  it("produces cost and latency scatter points in sensible units", () => {
    const cost = tradeoffPoints(metrics, "cost");
    expect(cost.find((p) => p.pipeline === "rag" && p.label === "overall")).toMatchObject({ x: 0.01, y: 40 });
    const latency = tradeoffPoints(metrics, "latency");
    expect(latency[0].x).toBe(2); // ms -> seconds
  });
  it("drops points with a missing axis", () => {
    const m = { rag: { ...metrics.rag!, overall: block({ cost_usd_mean: null }), by_category: {} } };
    expect(tradeoffPoints(m, "cost")).toEqual([]);
  });
  it("stacks failure labels per pipeline", () => {
    const { rows, labels } = failureStack(metrics);
    expect(labels).toEqual(["budget_loop", "retrieval_miss"]);
    expect(rows).toEqual([
      { pipeline: "rag", budget_loop: 0, retrieval_miss: 3 },
      { pipeline: "agent", budget_loop: 1, retrieval_miss: 0 },
    ]);
  });
  it("reports calls per pipeline", () => {
    expect(callsRows(metrics)).toEqual([
      { pipeline: "rag", llm: 1, tool: 0 },
      { pipeline: "agent", llm: 5.4, tool: 3.4 },
    ]);
  });
});

describe("evidence helpers", () => {
  const result = {
    citations: [
      { doc_id: "d1", page: 42, quote: "Deloitte Haskins" },
      { doc_id: "d2", page: 7, quote: "not in any block" },
    ],
    evidence: [
      { kind: "chunk", ref_id: "c1", text: "intro" },
      { kind: "triple", ref_id: "e1,e2", text: "Deloitte Haskins audits" },
      { kind: "triple", ref_id: "e3", text: "x" },
      { kind: "chunk", ref_id: "c9", text: "y" },
    ],
  } as unknown as AnswerResult;

  it("traces citations to evidence labels where the quote matches", () => {
    const chips = citationChips(result);
    expect(chips[0].label).toBe("E2");
    expect(chips[1].label).toBeNull();
  });
  it("splits answer text around [E#] markers", () => {
    expect(splitMarkers("Sharma [E1] and Verma [E2, E3].")).toEqual([
      { kind: "text", value: "Sharma " },
      { kind: "marker", value: "E1" },
      { kind: "text", value: " and Verma " },
      { kind: "marker", value: "E2,E3" },
      { kind: "text", value: "." },
    ]);
    expect(splitMarkers("no markers")).toEqual([{ kind: "text", value: "no markers" }]);
    expect(splitMarkers("")).toEqual([]);
  });
  it("collects edge ids from triple evidence only, splitting transactions", () => {
    expect(edgeIdsOf(result)).toEqual(["e1", "e2", "e3"]);
  });
  it("finds the edges that sit on gold evidence pages", () => {
    const edge = (id: string, doc_id: string, page: number): SubgraphEdge => ({
      id, type: "DIRECTOR_OF", source: "a", target: "b", label: "", fiscal_year: "", doc_id, page, quote: "",
    });
    const edges = [edge("e1", "d1", 5), edge("e2", "d1", 6), edge("e3", "", 5)];
    expect(goldEdgeIds(edges, [{ doc_id: "d1", page: 5 }])).toEqual(new Set(["e1"]));
    expect(goldEdgeIds(edges, null)).toEqual(new Set());
  });
});

describe("sample caveats", () => {
  it("warns about small samples and mixed splits, and stays quiet otherwise", () => {
    const m = (split: string, n: number) => ({ split, overall: { n } });
    expect(sampleCaveats({ rag: m("dev", 100), agent: m("dev", 120) })).toEqual([]);
    const small = sampleCaveats({ rag: m("dev", 5), agent: m("dev", 100) });
    expect(small).toHaveLength(1);
    expect(small[0]).toContain("rag: n=5");
    expect(small[0]).not.toContain("agent");
    const mixed = sampleCaveats({ rag: m("dev", 100), agent: m("test", 100) });
    expect(mixed[0]).toContain("different splits");
  });
});

describe("takeaways", () => {
  const mk = (llm: number, latency: number): MetricsBlock => block({ llm_calls_mean: llm, latency_median_ms: latency });
  const compare = (verdict: string, diff: number | null): CompareRunsOut => ({
    runs: {},
    questions: [],
    leaders: {},
    metrics: {
      rag: { run_id: "r", pipeline: "rag", split: "dev", question_version: "v1", git_commit: null, overall: mk(1, 9000), by_category: {} },
      agent: { run_id: "a", pipeline: "agent", split: "dev", question_version: "v1", git_commit: null, overall: mk(5.4, 57000), by_category: {} },
    },
    pairs: [{ metric: "correct", a: "agent", b: "rag", overall: { n: 5, diff, ci95: null, verdict }, by_category: {} }],
  });

  it("states the cost multiples and an accuracy claim only as strong as the verdict", () => {
    const [unclear] = takeaways(compare("no clear difference", -0.2));
    expect(unclear).toContain("5.4\u00d7 the LLM calls");
    expect(unclear).toContain("6.3\u00d7 the median latency");
    expect(unclear).toContain("no clear accuracy difference (-20 points)");
    expect(takeaways(compare("A better", 0.4))[0]).toContain("clearly more accurate (+40 points)");
    expect(takeaways(compare("B better", -0.4))[0]).toContain("clearly less accurate");
  });
  it("asks for a baseline when there is no RAG run, and for more runs when alone", () => {
    const noRag = { ...compare("A better", 0.1), metrics: { agent: compare("A better", 0.1).metrics.agent } };
    expect(takeaways(noRag)[0]).toContain("Select a RAG run");
    const alone = { ...compare("A better", 0.1), metrics: { rag: compare("A better", 0.1).metrics.rag }, pairs: [] };
    expect(takeaways(alone)[0]).toContain("more than one pipeline");
  });
  it("detects an all-zero cost axis", () => {
    expect(allZero([{ x: 0 }, { x: 0 }])).toBe(true);
    expect(allZero([{ x: 0 }, { x: 0.01 }])).toBe(false);
    expect(allZero([])).toBe(false);
  });
});
