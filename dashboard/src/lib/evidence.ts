import type { AnswerResult, Citation, SubgraphEdge } from "./types";

export interface CitationChip extends Citation {
  label: string | null; // "E3", when the quote can be traced to an evidence block
}

/** Which evidence block each citation came from. Labels are the evidence list order
 *  (E1 is the first item), which is how the pipelines assign them. */
export function citationChips(result: AnswerResult): CitationChip[] {
  return result.citations.map((c) => {
    const i = result.evidence.findIndex((e) => c.quote && e.text.includes(c.quote));
    return { ...c, label: i >= 0 ? `E${i + 1}` : null };
  });
}

/** Split an answer into text and [E#] markers so markers can render as chips. */
export function splitMarkers(text: string): { kind: "text" | "marker"; value: string }[] {
  const out: { kind: "text" | "marker"; value: string }[] = [];
  const re = /\[(E\d+(?:\s*,\s*E\d+)*)\]/g;
  let last = 0;
  for (const m of text.matchAll(re)) {
    const start = m.index ?? 0;
    if (start > last) out.push({ kind: "text", value: text.slice(last, start) });
    out.push({ kind: "marker", value: m[1].replace(/\s+/g, "") });
    last = start + m[0].length;
  }
  if (last < text.length) out.push({ kind: "text", value: text.slice(last) });
  return out;
}

/** Edge ids behind a result's graph evidence. A transaction's ref_id is "edgeA,edgeB". */
export function edgeIdsOf(result: AnswerResult): string[] {
  const ids = new Set<string>();
  for (const e of result.evidence) {
    if (e.kind !== "triple") continue;
    for (const part of e.ref_id.split(",")) if (part.trim()) ids.add(part.trim());
  }
  return [...ids];
}

/** Edges whose source page is one of the question's gold evidence pages. */
export function goldEdgeIds(
  edges: SubgraphEdge[],
  gold: { doc_id: string; page: number }[] | null | undefined,
): Set<string> {
  const pages = new Set((gold ?? []).map((g) => `${g.doc_id}:${g.page}`));
  return new Set(edges.filter((e) => e.doc_id && pages.has(`${e.doc_id}:${e.page}`)).map((e) => e.id));
}
