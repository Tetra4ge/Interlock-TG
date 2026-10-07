"use client";

import { useRouter } from "next/navigation";
import { PIPELINES, PIPELINE_ORDER } from "@/lib/pipelines";
import { runsFor, selectionQuery, type Selection } from "@/lib/runs";
import type { PipelineKey, RunOut } from "@/lib/types";

/** One dropdown per pipeline. The choice lives in the URL, so a view can be shared. */
export default function RunSelector({
  runs,
  selection,
  basePath,
  keep = {},
}: {
  runs: RunOut[];
  selection: Selection;
  basePath: string;
  keep?: Record<string, string>; // other query parameters to preserve, e.g. { q: "Q-SF-0001" }
}) {
  const router = useRouter();

  function choose(key: PipelineKey, runId: string) {
    const next: Selection = { ...selection };
    if (runId) next[key] = runId;
    else delete next[key];
    const usp = new URLSearchParams(selectionQuery(next).slice(1));
    for (const [k, v] of Object.entries(keep)) usp.set(k, v);
    const qs = usp.toString();
    router.push(qs ? `${basePath}?${qs}` : basePath);
  }

  return (
    <div className="flex flex-wrap items-end gap-3 text-xs">
      {PIPELINE_ORDER.map((key) => {
        const options = runsFor(runs, key);
        return (
          <label key={key} className="flex flex-col gap-1">
            <span className="flex items-center gap-1.5 font-medium">
              <span
                aria-hidden
                className="inline-block h-2 w-2 rounded-full"
                style={{ backgroundColor: PIPELINES[key].color }}
              />
              {PIPELINES[key].label} run
            </span>
            <select
              value={selection[key] ?? ""}
              onChange={(e) => choose(key, e.target.value)}
              disabled={options.length === 0}
              className="max-w-56 rounded-md border border-border bg-surface-muted px-2 py-1.5 text-xs text-foreground"
            >
              <option value="">{options.length ? "none" : "no runs yet"}</option>
              {options.map((r) => (
                <option key={r.run_id} value={r.run_id}>
                  {r.run_id} ({r.split}, {r.n_results} q)
                </option>
              ))}
            </select>
          </label>
        );
      })}
    </div>
  );
}
