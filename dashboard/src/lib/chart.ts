import { PIPELINE_ORDER } from "./pipelines";
import type { CompareRunsOut, MetricsBlock, PipelineKey } from "./types";

export interface AccuracyRow {
  category: string;
  n: number;
  [pipeline: string]: number | string | [number, number] | null;
}

/** Grouped-bar data: one row per category (plus "overall"), one value per pipeline,
 *  and an error-bar pair [mean - lower, upper - mean] for the 95% interval. */
export function accuracyRows(metrics: CompareRunsOut["metrics"]): AccuracyRow[] {
  const keys = PIPELINE_ORDER.filter((k) => metrics[k]);
  const categories = new Set<string>();
  for (const k of keys) Object.keys(metrics[k]!.by_category).forEach((c) => categories.add(c));

  const rowFor = (category: string, pick: (k: PipelineKey) => MetricsBlock | undefined): AccuracyRow => {
    const row: AccuracyRow = { category, n: 0 };
    for (const k of keys) {
      const block = pick(k);
      row.n = Math.max(row.n, block?.n ?? 0);
      const mean = block?.correct_mean ?? null;
      const ci = block?.correct_ci95 ?? null;
      row[k] = mean;
      row[`${k}_err`] = mean !== null && ci ? [Math.max(0, mean - ci[0]), Math.max(0, ci[1] - mean)] : null;
    }
    return row;
  };

  return [
    rowFor("overall", (k) => metrics[k]?.overall),
    ...[...categories].sort().map((c) => rowFor(c, (k) => metrics[k]?.by_category[c])),
  ];
}

export interface ScatterPoint {
  pipeline: PipelineKey;
  label: string;
  x: number;
  y: number;
  n: number;
}

/** One point per pipeline and category: x is the cost or latency, y is accuracy. */
export function tradeoffPoints(
  metrics: CompareRunsOut["metrics"],
  x: "cost" | "latency",
): ScatterPoint[] {
  const points: ScatterPoint[] = [];
  for (const key of PIPELINE_ORDER) {
    const m = metrics[key];
    if (!m) continue;
    const blocks: [string, MetricsBlock][] = [["overall", m.overall], ...Object.entries(m.by_category)];
    for (const [label, b] of blocks) {
      const xv = x === "cost" ? b.cost_usd_mean : b.latency_median_ms;
      if (b.correct_mean === null || xv === null) continue;
      points.push({ pipeline: key, label, x: x === "latency" ? xv / 1000 : xv, y: b.correct_mean * 100, n: b.n });
    }
  }
  return points;
}

export interface FailureRow {
  label: string;
  [pipeline: string]: number | string;
}

/** Stacked-bar data: one bar per pipeline, one segment per failure label. */
export function failureStack(metrics: CompareRunsOut["metrics"]): {
  rows: Record<string, number | string>[];
  labels: string[];
} {
  const labels = new Set<string>();
  for (const key of PIPELINE_ORDER) {
    Object.keys(metrics[key]?.overall.failures ?? {}).forEach((l) => labels.add(l));
  }
  const ordered = [...labels].sort();
  const rows = PIPELINE_ORDER.filter((k) => metrics[k]).map((k) => {
    const row: Record<string, number | string> = { pipeline: k };
    for (const l of ordered) row[l] = metrics[k]!.overall.failures[l] ?? 0;
    return row;
  });
  return { rows, labels: ordered };
}

export function callsRows(metrics: CompareRunsOut["metrics"]): { pipeline: string; llm: number; tool: number }[] {
  return PIPELINE_ORDER.filter((k) => metrics[k]).map((k) => ({
    pipeline: k,
    llm: metrics[k]!.overall.llm_calls_mean ?? 0,
    tool: metrics[k]!.overall.tool_calls_mean ?? 0,
  }));
}
