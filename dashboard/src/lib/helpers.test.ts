import { describe, expect, it } from "vitest";
import { accuracyRows, allZero, callsRows, failureStack, takeaways, tradeoffPoints } from "./chart";
import { NO_FILTERS, UNLABELLED, distinct, failureRows, filterFailures, labelColor } from "./failures";
import { matchQuestions } from "../components/QuestionPicker";
import { edgeUsers, layoutGraph } from "./graph";
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

describe("failures", () => {
  const cell = (correct: number | null, label: string | null, answer = "x") => ({
    run_id: "r", status: "ok" as const, answer_short: answer, correct, failure_label: label,
    cost_usd: 0, latency_ms: 0, tool_calls: 0,
  });
  const compare = {
    runs: {}, metrics: {}, pairs: [], leaders: {},
    questions: [
      { qid: "q1", question: "Who audits Tata Steel?", category: "single_fact", cells: { rag: cell(0, "retrieval_miss", "Nobody"), agent: cell(1, null) } },
      { qid: "q2", question: "Total RPT of Tata Motors", category: "numerical", cells: { rag: cell(0.5, null), graphrag: cell(null, null) } },
      { qid: "q3", question: "Fine question", category: "single_fact", cells: { rag: cell(1, null) } },
    ],
  } as unknown as CompareRunsOut;

  it("lists only pairs scored below fully correct, labelling unlabelled ones", () => {
    const rows = failureRows(compare);
    expect(rows.map((r) => r.key)).toEqual(["q1:rag", "q2:rag"]);
    expect(rows[0].label).toBe("retrieval_miss");
    expect(rows[1].label).toBe(UNLABELLED); // partial credit but no label
  });
  it("filters by search, category, pipeline and label together", () => {
    const rows = failureRows(compare);
    expect(filterFailures(rows, NO_FILTERS)).toHaveLength(2);
    expect(filterFailures(rows, { ...NO_FILTERS, search: "TATA STEEL" }).map((r) => r.qid)).toEqual(["q1"]);
    expect(filterFailures(rows, { ...NO_FILTERS, search: "nobody" }).map((r) => r.qid)).toEqual(["q1"]);
    expect(filterFailures(rows, { ...NO_FILTERS, category: "numerical" }).map((r) => r.qid)).toEqual(["q2"]);
    expect(filterFailures(rows, { ...NO_FILTERS, pipeline: "agent" })).toEqual([]);
    expect(filterFailures(rows, { ...NO_FILTERS, label: "retrieval_miss", category: "numerical" })).toEqual([]);
  });
  it("offers each filter value once, sorted", () => {
    expect(distinct(failureRows(compare), (r) => r.category)).toEqual(["numerical", "single_fact"]);
  });
  it("gives each label a stable colour", () => {
    const labels = ["a", "b"];
    expect(labelColor("a", labels)).toBe(labelColor("a", labels));
    expect(labelColor("a", labels)).not.toBe(labelColor("b", labels));
  });
});

describe("graph layout", () => {
  const node = (id: string, type: string, label = id) => ({ id, type, label });
  const edge = (id: string, source: string, target: string) => ({
    id, type: "DIRECTOR_OF", source, target, label: "", fiscal_year: "", doc_id: "", page: 0, quote: "",
  });
  const nodes = [node("C:2", "Company"), node("P:1", "Person"), node("C:1", "Company"), node("A:1", "AuditFirm")];

  it("puts people, companies and firms in left-to-right columns", () => {
    const l = layoutGraph(nodes, []);
    const x = (id: string) => l.nodes.find((n) => n.id === id)!.x;
    expect(x("P:1")).toBeLessThan(x("C:1"));
    expect(x("C:1")).toBe(x("C:2"));
    expect(x("C:1")).toBeLessThan(x("A:1"));
    expect(l.nodes).toHaveLength(4);
  });
  it("stacks a column's nodes at distinct heights, ordered by label", () => {
    const l = layoutGraph(nodes, []);
    const [a, b] = l.nodes.filter((n) => n.type === "Company").sort((p, q) => p.y - q.y);
    expect(a.id).toBe("C:1");
    expect(b.id).toBe("C:2");
    expect(a.y).not.toBe(b.y);
  });
  it("is deterministic whatever order the nodes arrive in", () => {
    const a = layoutGraph(nodes, []);
    const b = layoutGraph([...nodes].reverse(), []);
    const pos = (l: typeof a) => Object.fromEntries(l.nodes.map((n) => [n.id, [n.x, n.y]]));
    expect(pos(a)).toEqual(pos(b));
  });
  it("drops edges whose endpoints are missing and offsets parallel edges", () => {
    const l = layoutGraph(nodes, [edge("e1", "P:1", "C:1"), edge("e2", "P:1", "C:1"), edge("e3", "P:1", "GHOST")]);
    expect(l.edges.map((e) => e.id).sort()).toEqual(["e1", "e2"]);
    const bends = l.edges.map((e) => e.bend);
    expect(bends[0]).not.toBe(bends[1]);
    expect(bends[0] + bends[1]).toBe(0); // symmetric around the straight line
  });
  it("a single edge is not bent", () => {
    expect(layoutGraph(nodes, [edge("e1", "P:1", "C:1")]).edges[0].bend).toBe(0);
  });
  it("copes with an empty graph", () => {
    const l = layoutGraph([], []);
    expect(l.nodes).toEqual([]);
    expect(l.height).toBeGreaterThan(0);
    expect(l.width).toBeGreaterThan(0);
  });
  it("lists which pipelines used each edge", () => {
    expect(edgeUsers([{ id: "e1" }, { id: "e2" }], { rag: [], graphrag: ["e1"], agent: ["e1", "e2"] })).toEqual({
      e1: ["graphrag", "agent"],
      e2: ["agent"],
    });
  });
});

describe("question picker search", () => {
  const rows = [
    { qid: "Q-SF-0001", question: "Who audits Tata Motors?", category: "single_fact", cells: {} },
    { qid: "Q-NU-0002", question: "Total related-party sales of Tata Steel", category: "numerical", cells: {} },
  ];
  it("matches question text, id and category, ignoring case and padding", () => {
    expect(matchQuestions(rows, "  TATA STEEL ").map((r) => r.qid)).toEqual(["Q-NU-0002"]);
    expect(matchQuestions(rows, "q-sf").map((r) => r.qid)).toEqual(["Q-SF-0001"]);
    expect(matchQuestions(rows, "numerical").map((r) => r.qid)).toEqual(["Q-NU-0002"]);
    expect(matchQuestions(rows, "zzz")).toEqual([]);
    expect(matchQuestions(rows, "")).toHaveLength(2);
  });
});
