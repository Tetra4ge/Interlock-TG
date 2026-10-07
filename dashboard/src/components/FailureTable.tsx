"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { Badge, PipelineName } from "@/components/ui";
import { NO_FILTERS, distinct, filterFailures, type FailureFilters, type FailureRow } from "@/lib/failures";
import { humanize } from "@/lib/format";

function Select({
  label,
  value,
  options,
  onChange,
  format = (s: string) => s,
}: {
  label: string;
  value: string;
  options: string[];
  onChange: (v: string) => void;
  format?: (s: string) => string;
}) {
  return (
    <label className="flex flex-col gap-1 text-xs">
      <span className="font-medium">{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)} className="rounded-md border border-border bg-surface px-2 py-1.5">
        <option value="">All</option>
        {options.map((o) => (
          <option key={o} value={o}>
            {format(o)}
          </option>
        ))}
      </select>
    </label>
  );
}

/** Failing (question, pipeline) pairs with filters; each row links to the inspector. */
export default function FailureTable({
  rows,
  selectionQuery,
}: {
  rows: FailureRow[];
  selectionQuery: string; // "?rag=..&agent=.." to carry the run choice into the inspector
}) {
  const [filters, setFilters] = useState<FailureFilters>(NO_FILTERS);
  const shown = useMemo(() => filterFailures(rows, filters), [rows, filters]);
  const set = (patch: Partial<FailureFilters>) => setFilters((f) => ({ ...f, ...patch }));

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-end gap-3">
        <label className="flex min-w-48 flex-1 flex-col gap-1 text-xs">
          <span className="font-medium">Search</span>
          <input
            value={filters.search}
            onChange={(e) => set({ search: e.target.value })}
            placeholder="question text, answer or id"
            className="rounded-md border border-border bg-surface px-2 py-1.5"
          />
        </label>
        <Select label="Category" value={filters.category} options={distinct(rows, (r) => r.category)} onChange={(category) => set({ category })} format={humanize} />
        <Select label="Pipeline" value={filters.pipeline} options={distinct(rows, (r) => r.pipeline)} onChange={(pipeline) => set({ pipeline })} />
        <Select label="Failure" value={filters.label} options={distinct(rows, (r) => r.label)} onChange={(label) => set({ label })} format={humanize} />
        <button onClick={() => setFilters(NO_FILTERS)} className="rounded-md border border-border px-2 py-1.5 text-xs hover:bg-surface-muted">
          Clear
        </button>
      </div>

      <p className="mb-2 text-xs text-muted" aria-live="polite">
        Showing {shown.length} of {rows.length} failures.
      </p>
      {shown.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted">
          {rows.length === 0 ? "No failures in the selected runs." : "No failures match these filters."}
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-muted">
              <tr>
                <th className="pb-1">Question</th><th>Category</th><th>Pipeline</th><th>Failure</th><th>Answered</th><th />
              </tr>
            </thead>
            <tbody>
              {shown.map((r) => (
                <tr key={r.key} className="border-t border-border align-top">
                  <td className="max-w-md py-1.5 pr-3">
                    <div>{r.question}</div>
                    <div className="text-xs text-muted">{r.qid}</div>
                  </td>
                  <td className="pr-3">{humanize(r.category)}</td>
                  <td className="pr-3"><PipelineName pipeline={r.pipeline} /></td>
                  <td className="pr-3"><Badge tone="bad">{humanize(r.label)}</Badge></td>
                  <td className="max-w-48 pr-3 text-muted">{r.answer || `(${r.status})`}</td>
                  <td>
                    <Link
                      href={`/inspector${selectionQuery}${selectionQuery ? "&" : "?"}q=${encodeURIComponent(r.qid)}`}
                      className="whitespace-nowrap text-xs font-medium underline"
                    >
                      Inspect
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
