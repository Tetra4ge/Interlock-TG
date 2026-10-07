import { PIPELINE_ORDER } from "./pipelines";
import type { CompareRunsOut, PipelineKey } from "./types";

export interface FailureRow {
  key: string;
  qid: string;
  question: string;
  category: string;
  pipeline: PipelineKey;
  label: string; // failure label, or "unlabelled" when scored wrong without one
  status: string;
  answer: string;
}

export const UNLABELLED = "unlabelled";

/** Every (question, pipeline) pair that was scored below fully correct. */
export function failureRows(compare: CompareRunsOut): FailureRow[] {
  const rows: FailureRow[] = [];
  for (const q of compare.questions) {
    for (const pipeline of PIPELINE_ORDER) {
      const cell = q.cells[pipeline];
      if (!cell || cell.correct === null || cell.correct >= 1) continue;
      rows.push({
        key: `${q.qid}:${pipeline}`,
        qid: q.qid,
        question: q.question,
        category: q.category,
        pipeline,
        label: cell.failure_label ?? UNLABELLED,
        status: cell.status,
        answer: cell.answer_short,
      });
    }
  }
  return rows;
}

export interface FailureFilters {
  search: string;
  category: string; // "" = all
  pipeline: string;
  label: string;
}

export const NO_FILTERS: FailureFilters = { search: "", category: "", pipeline: "", label: "" };

export function filterFailures(rows: FailureRow[], f: FailureFilters): FailureRow[] {
  const needle = f.search.trim().toLowerCase();
  return rows.filter(
    (r) =>
      (!f.category || r.category === f.category) &&
      (!f.pipeline || r.pipeline === f.pipeline) &&
      (!f.label || r.label === f.label) &&
      (!needle ||
        r.question.toLowerCase().includes(needle) ||
        r.answer.toLowerCase().includes(needle) ||
        r.qid.toLowerCase().includes(needle)),
  );
}

export function distinct(rows: FailureRow[], pick: (r: FailureRow) => string): string[] {
  return [...new Set(rows.map(pick))].sort();
}

/** A stable colour per failure label for the stacked chart. */
const PALETTE = ["#ef4444", "#f59e0b", "#14b8a6", "#6366f1", "#ec4899", "#84cc16", "#0ea5e9", "#a855f7", "#78716c"];
export function labelColor(label: string, all: string[]): string {
  const i = all.indexOf(label);
  return PALETTE[(i < 0 ? all.length : i) % PALETTE.length];
}
