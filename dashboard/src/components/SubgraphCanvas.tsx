"use client";

import { useEffect, useMemo, useState } from "react";
import { fetchSubgraph } from "@/lib/api";
import { humanize, shortId } from "@/lib/format";
import { edgeUsers, layoutGraph, type PlacedEdge } from "@/lib/graph";
import { goldEdgeIds } from "@/lib/evidence";
import { PIPELINES, PIPELINE_ORDER } from "@/lib/pipelines";
import type { PipelineKey, SubgraphOut } from "@/lib/types";

const SHARED_COLOR = "#475569";
const GOLD_COLOR = "#f59e0b";
const NODE_COLORS: Record<string, string> = {
  Person: "#0ea5e9",
  Company: "#14b8a6",
  RelatedPartyTxn: "#f97316",
  AuditFirm: "#a855f7",
};

type State =
  | { status: "empty" }
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: SubgraphOut };

interface Loaded {
  key: string; // the edge ids this result is for
  result: { ok: true; data: SubgraphOut } | { ok: false; error: string };
}

function edgeColor(users: string[]): string {
  if (users.length === 1) return PIPELINES[users[0] as PipelineKey]?.color ?? SHARED_COLOR;
  return SHARED_COLOR;
}

/** The knowledge-graph facts the answers were built from. Edges are coloured by the
 *  pipeline that retrieved them (grey when several did) and edges on the question's
 *  gold evidence pages get an amber halo. Click a node or edge for its source. */
export default function SubgraphCanvas({
  edgeIdsByPipeline,
  gold,
}: {
  edgeIdsByPipeline: Partial<Record<PipelineKey, string[]>>;
  gold: { doc_id: string; page: number }[] | null;
}) {
  const allIds = useMemo(
    () => [...new Set(Object.values(edgeIdsByPipeline).flat())].sort(),
    [edgeIdsByPipeline],
  );
  const key = allIds.join(",");
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [pick, setPick] = useState<{ key: string; id: string } | null>(null);

  // State is derived: a result only counts for the edge ids it was fetched for, so a new
  // question shows "loading" and drops its selection without any synchronous setState.
  const state: State = !key
    ? { status: "empty" }
    : loaded?.key === key
      ? loaded.result.ok
        ? { status: "ready", data: loaded.result.data }
        : { status: "error", message: loaded.result.error }
      : { status: "loading" };
  const selected = pick?.key === key ? pick.id : null;

  useEffect(() => {
    if (!key) return;
    let cancelled = false;
    fetchSubgraph(key.split(",")).then((res) => {
      if (!cancelled) setLoaded({ key, result: res.ok ? { ok: true, data: res.data } : { ok: false, error: res.error } });
    });
    return () => {
      cancelled = true;
    };
  }, [key]);

  const ready = state.status === "ready" ? state.data : null;
  const layout = useMemo(() => (ready ? layoutGraph(ready.nodes, ready.edges) : null), [ready]);
  const users = useMemo(() => (ready ? edgeUsers(ready.edges, edgeIdsByPipeline) : {}), [ready, edgeIdsByPipeline]);
  const goldIds = useMemo(() => (ready ? goldEdgeIds(ready.edges, gold) : new Set<string>()), [ready, gold]);
  const picked = ready?.edges.find((e) => e.id === selected) ?? null;

  if (state.status === "empty") {
    return <p className="text-sm text-muted">None of these answers retrieved graph facts, so there is no subgraph to draw.</p>;
  }
  if (state.status === "loading") return <p className="text-sm text-muted" aria-busy="true">Loading the subgraph…</p>;
  if (state.status === "error") {
    return (
      <div role="status" className="rounded-lg border border-amber-300 bg-warn-bg p-3 text-sm text-warn-fg">
        The subgraph could not be loaded: {state.message}
        <p className="mt-1 text-xs">The evidence text each pipeline used is still shown on its card.</p>
      </div>
    );
  }
  if (!layout || !ready) return null;
  if (layout.nodes.length === 0) {
    return (
      <p className="text-sm text-muted">
        The graph returned none of the {ready.requested} requested facts (found {ready.found}).
      </p>
    );
  }

  const path = (e: PlacedEdge) => {
    const mx = (e.x1 + e.x2) / 2;
    const my = (e.y1 + e.y2) / 2 + e.bend;
    return `M${e.x1},${e.y1} Q${mx},${my} ${e.x2},${e.y2}`;
  };

  return (
    <div>
      <div className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-xs">
        {PIPELINE_ORDER.filter((k) => edgeIdsByPipeline[k]?.length).map((k) => (
          <span key={k} className="inline-flex items-center gap-1.5">
            <span className="inline-block h-0.5 w-5" style={{ backgroundColor: PIPELINES[k].color }} />
            only {PIPELINES[k].short}
          </span>
        ))}
        <span className="inline-flex items-center gap-1.5"><span className="inline-block h-0.5 w-5" style={{ backgroundColor: SHARED_COLOR }} />several pipelines</span>
        {gold ? <span className="inline-flex items-center gap-1.5"><span className="inline-block h-1.5 w-5 rounded" style={{ backgroundColor: GOLD_COLOR }} />on gold evidence page</span> : null}
        <span className="text-muted">{ready.found} of {ready.requested} facts found</span>
      </div>
      <div className="overflow-x-auto rounded-lg border border-border bg-surface-muted/40">
        <svg role="img" aria-label="Knowledge graph of the facts used by the answers" viewBox={`0 0 ${layout.width} ${layout.height}`} className="mx-auto block w-full" style={{ maxWidth: Math.max(layout.width, 480), minHeight: layout.height }}>
          <defs>
            <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
              <path d="M0,0 L10,5 L0,10 z" fill="context-stroke" />
            </marker>
          </defs>
          {layout.edges.map((e) => {
            const isGold = goldIds.has(e.id);
            const active = selected === e.id;
            return (
              <g key={e.id} role="button" tabIndex={0} aria-label={`${e.type} edge, ${e.label}`} className="cursor-pointer outline-none" onClick={() => setPick(active ? null : { key, id: e.id })} onKeyDown={(ev) => (ev.key === "Enter" || ev.key === " ") && setPick(active ? null : { key, id: e.id })}>
                {isGold ? <path d={path(e)} fill="none" stroke={GOLD_COLOR} strokeOpacity={0.45} strokeWidth={9} /> : null}
                <path d={path(e)} fill="none" stroke="transparent" strokeWidth={14} />
                <path d={path(e)} fill="none" stroke={edgeColor(users[e.id] ?? [])} strokeWidth={active ? 3.5 : 2} markerEnd="url(#arrow)" />
              </g>
            );
          })}
          {layout.nodes.map((n) => (
            <g key={n.id} transform={`translate(${n.x},${n.y})`}>
              <circle r={13} fill={NODE_COLORS[n.type] ?? "#94a3b8"} stroke="var(--background)" strokeWidth={2} />
              <title>{`${n.label} (${n.type})`}</title>
              <text y={30} textAnchor="middle" fontSize={11} fill="currentColor">
                {n.label.length > 26 ? `${n.label.slice(0, 25)}…` : n.label}
              </text>
            </g>
          ))}
        </svg>
      </div>
      {picked ? (
        <div className="mt-2 rounded-lg border border-border bg-surface p-3 text-xs" aria-live="polite">
          <p className="font-semibold">{humanize(picked.type)} · {picked.label}{picked.fiscal_year ? ` · ${picked.fiscal_year}` : ""}</p>
          <p className="text-muted">used by {(users[picked.id] ?? []).map((k) => PIPELINES[k as PipelineKey]?.short ?? k).join(", ") || "no pipeline"}{goldIds.has(picked.id) ? " · on a gold evidence page" : ""}</p>
          {picked.doc_id ? <p className="mt-1">Source: doc {shortId(picked.doc_id)}, p.{picked.page}</p> : <p className="mt-1 text-muted">No source page recorded for this relation.</p>}
          {picked.quote ? <blockquote className="mt-1 border-l-2 border-border pl-2 italic">{picked.quote}</blockquote> : null}
        </div>
      ) : (
        <p className="mt-2 text-xs text-muted">Click an edge to see its source page and quote.</p>
      )}
    </div>
  );
}
