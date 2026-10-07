import { PIPELINE_ORDER, isPipelineKey } from "./pipelines";
import type { PipelineKey, RunOut } from "./types";

export type Selection = Partial<Record<PipelineKey, string>>;

/** The default run for each pipeline: the newest one on the given split (the API
 *  lists runs newest first). Falls back to any split when that split has none, so a
 *  pipeline with only a dev run still shows up. */
export function defaultSelection(runs: RunOut[], split?: string): Selection {
  const out: Selection = {};
  for (const key of PIPELINE_ORDER) {
    const mine = runs.filter((r) => r.pipeline === key && r.n_results > 0);
    const preferred = split ? mine.find((r) => r.split === split) : undefined;
    const chosen = preferred ?? mine[0];
    if (chosen) out[key] = chosen.run_id;
  }
  return out;
}

type Params = Record<string, string | string[] | undefined>;

function first(v: string | string[] | undefined): string | undefined {
  return Array.isArray(v) ? v[0] : v;
}

/** Selection from the URL (?rag=..&graphrag=..&agent=..), ignoring unknown run ids
 *  so a stale link degrades to the default instead of an error page. */
export function selectionFromParams(params: Params, runs: RunOut[], split?: string): Selection {
  const chosen: Selection = {};
  for (const key of PIPELINE_ORDER) {
    const id = first(params[key]);
    if (id && runs.some((r) => r.run_id === id && r.pipeline === key)) chosen[key] = id;
  }
  const defaults = defaultSelection(runs, split);
  const explicit = Object.keys(chosen).length > 0;
  // An explicit choice is respected exactly; with none, use the defaults.
  return explicit ? chosen : defaults;
}

export function selectionQuery(selection: Selection): string {
  const usp = new URLSearchParams();
  for (const key of PIPELINE_ORDER) {
    const id = selection[key];
    if (id) usp.set(key, id);
  }
  const s = usp.toString();
  return s ? `?${s}` : "";
}

export function runsFor(runs: RunOut[], pipeline: string): RunOut[] {
  return runs.filter((r) => r.pipeline === pipeline && isPipelineKey(r.pipeline) && r.n_results > 0);
}
