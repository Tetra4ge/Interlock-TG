"use client";

import { useEffect, useState } from "react";
import { fetchDocumentPage, pdfUrl } from "@/lib/api";
import { shortId } from "@/lib/format";
import type { CitationChip } from "@/lib/evidence";
import type { DocumentPage, EvidenceItem } from "@/lib/types";

type Page =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: DocumentPage };

function SourcePage({ docId, page }: { docId: string; page: number }) {
  const [state, setState] = useState<Page>({ status: "idle" });

  function load() {
    setState({ status: "loading" });
    fetchDocumentPage(docId, page).then((res) =>
      setState(res.ok ? { status: "ready", data: res.data } : { status: "error", message: res.error }),
    );
  }

  return (
    <div className="mt-2">
      <div className="flex flex-wrap items-center gap-3 text-xs">
        <button onClick={load} className="rounded-md border border-border px-2 py-1 font-medium hover:bg-surface-muted">
          Show source page text
        </button>
        <a href={pdfUrl(docId, page)} target="_blank" rel="noopener noreferrer" className="font-medium underline">
          Open PDF at p.{page}
        </a>
      </div>
      {state.status === "loading" ? <p className="mt-2 text-xs text-muted">Loading…</p> : null}
      {state.status === "error" ? (
        <p role="status" className="mt-2 text-xs text-muted">
          Source text unavailable: {state.message}
        </p>
      ) : null}
      {state.status === "ready" ? (
        <div className="mt-2">
          <p className="text-xs text-muted">
            {[state.data.company_id, state.data.doc_type, state.data.fiscal_year].filter(Boolean).join(" · ")} · page {state.data.page}
          </p>
          <pre className="mt-1 max-h-60 overflow-auto whitespace-pre-wrap rounded-md bg-surface-muted p-2 text-xs">{state.data.text}</pre>
        </div>
      ) : null}
    </div>
  );
}

/** What one evidence label stands for: the evidence text the model saw, the citations
 *  that point at it, and a way to open the original page. */
export default function CitationDrawer({
  label,
  evidence,
  chips,
  onClose,
}: {
  label: string;
  evidence: EvidenceItem | undefined;
  chips: CitationChip[];
  onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const cited = chips.filter((c) => c.label === label);
  return (
    <div role="dialog" aria-label={`Evidence ${label}`} className="mt-3 rounded-lg border border-border bg-surface p-3 text-xs shadow-md">
      <div className="mb-2 flex items-center justify-between">
        <p className="font-semibold">
          Evidence {label} {evidence ? <span className="font-normal text-muted">({evidence.kind})</span> : null}
        </p>
        <button onClick={onClose} aria-label="Close evidence" className="rounded px-1.5 text-muted hover:bg-surface-muted">
          ✕
        </button>
      </div>
      {evidence ? (
        <pre className="max-h-40 overflow-auto whitespace-pre-wrap rounded-md bg-surface-muted p-2">{evidence.text}</pre>
      ) : (
        <p className="text-muted">That evidence item is not part of this answer.</p>
      )}
      {cited.length === 0 ? (
        <p className="mt-2 text-muted">No citation points at this block.</p>
      ) : (
        cited.map((c, i) => (
          <div key={i} className="mt-2 border-t border-border pt-2">
            <p>
              Cited: doc {shortId(c.doc_id)}, p.{c.page}
            </p>
            {c.quote ? <blockquote className="mt-1 border-l-2 border-border pl-2 italic">“{c.quote}”</blockquote> : null}
            {c.doc_id ? <SourcePage docId={c.doc_id} page={c.page} /> : <p className="mt-1 text-muted">No source document recorded (computed result).</p>}
          </div>
        ))
      )}
    </div>
  );
}
