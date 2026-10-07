"use client";

import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { humanize } from "@/lib/format";
import type { QuestionRow } from "@/lib/types";

export function matchQuestions(rows: QuestionRow[], needle: string): QuestionRow[] {
  const n = needle.trim().toLowerCase();
  if (!n) return rows;
  return rows.filter(
    (r) => r.question.toLowerCase().includes(n) || r.qid.toLowerCase().includes(n) || r.category.includes(n),
  );
}

/** Searchable list of the questions the selected runs have in common. */
export default function QuestionPicker({
  rows,
  selected,
  basePath,
  query,
}: {
  rows: QuestionRow[];
  selected: string | null;
  basePath: string;
  query: Record<string, string>; // the rest of the URL (runs, gold) to keep
}) {
  const router = useRouter();
  const [needle, setNeedle] = useState("");
  const shown = useMemo(() => matchQuestions(rows, needle), [rows, needle]);

  function pick(qid: string) {
    const usp = new URLSearchParams(query);
    usp.set("q", qid);
    router.push(`${basePath}?${usp.toString()}`);
  }

  return (
    <div>
      <label className="flex flex-col gap-1 text-xs">
        <span className="font-medium">Find a question</span>
        <input value={needle} onChange={(e) => setNeedle(e.target.value)} placeholder="search text, id or category" className="rounded-md border border-border bg-surface px-2 py-1.5" />
      </label>
      <p className="my-1 text-xs text-muted" aria-live="polite">{shown.length} of {rows.length} questions</p>
      <ul className="max-h-72 overflow-auto rounded-lg border border-border" role="listbox" aria-label="Questions">
        {shown.map((r) => (
          <li key={r.qid} role="option" aria-selected={r.qid === selected}>
            <button
              onClick={() => pick(r.qid)}
              className={`w-full border-b border-border px-3 py-2 text-left text-sm last:border-b-0 hover:bg-surface-muted ${r.qid === selected ? "bg-surface-muted font-medium" : ""}`}
            >
              {r.question}
              <span className="block text-xs text-muted">{r.qid} · {humanize(r.category)}</span>
            </button>
          </li>
        ))}
        {shown.length === 0 ? <li className="px-3 py-4 text-center text-sm text-muted">No questions match.</li> : null}
      </ul>
    </div>
  );
}
