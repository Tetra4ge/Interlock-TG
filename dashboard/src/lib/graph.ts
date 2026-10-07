import type { SubgraphEdge, SubgraphNode } from "./types";

export interface PlacedNode extends SubgraphNode {
  x: number;
  y: number;
}

export interface PlacedEdge extends SubgraphEdge {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  /** Sideways shift so parallel edges (the same pair in several fiscal years) do not overlap. */
  bend: number;
}

export interface Layout {
  nodes: PlacedNode[];
  edges: PlacedEdge[];
  width: number;
  height: number;
}

// People on the left, companies in the middle, then transactions and firms.
const COLUMN_ORDER = ["Person", "Company", "RelatedPartyTxn", "AuditFirm"];
const COLUMN_GAP = 220;
const ROW_GAP = 64;
const MARGIN_X = 90;
const MARGIN_Y = 40;
const MIN_HEIGHT = 240;
const BEND_STEP = 14;

export function columnOf(type: string): number {
  const i = COLUMN_ORDER.indexOf(type);
  return i === -1 ? COLUMN_ORDER.length : i;
}

/** A deterministic column layout: the same graph always draws the same way, and it
 *  needs no physics library. Edges whose endpoints are missing are dropped. */
export function layoutGraph(nodes: SubgraphNode[], edges: SubgraphEdge[]): Layout {
  const used = [...new Set(nodes.map((n) => columnOf(n.type)))].sort((a, b) => a - b);
  const columns = new Map<number, SubgraphNode[]>();
  for (const n of nodes) {
    const c = columnOf(n.type);
    columns.set(c, [...(columns.get(c) ?? []), n]);
  }
  const tallest = Math.max(1, ...[...columns.values()].map((c) => c.length));
  const height = Math.max(MIN_HEIGHT, MARGIN_Y * 2 + (tallest - 1) * ROW_GAP);
  const width = MARGIN_X * 2 + Math.max(0, used.length - 1) * COLUMN_GAP;

  const placed = new Map<string, PlacedNode>();
  for (const [c, group] of columns) {
    const x = MARGIN_X + used.indexOf(c) * COLUMN_GAP;
    const sorted = [...group].sort((a, b) => a.label.localeCompare(b.label) || a.id.localeCompare(b.id));
    const span = (sorted.length - 1) * ROW_GAP;
    sorted.forEach((n, i) => {
      placed.set(n.id, { ...n, x, y: height / 2 - span / 2 + i * ROW_GAP });
    });
  }

  const groups = new Map<string, SubgraphEdge[]>();
  for (const e of edges) {
    if (!placed.has(e.source) || !placed.has(e.target)) continue;
    const key = [e.source, e.target].sort().join("|");
    groups.set(key, [...(groups.get(key) ?? []), e]);
  }
  const placedEdges: PlacedEdge[] = [];
  for (const group of groups.values()) {
    group.forEach((e, i) => {
      const s = placed.get(e.source)!;
      const t = placed.get(e.target)!;
      placedEdges.push({ ...e, x1: s.x, y1: s.y, x2: t.x, y2: t.y, bend: (i - (group.length - 1) / 2) * BEND_STEP });
    });
  }
  return { nodes: [...placed.values()], edges: placedEdges, width: Math.max(width, MARGIN_X * 2), height };
}

/** Which pipelines used each edge, for colouring: [] = none known. */
export function edgeUsers(
  edges: { id: string }[],
  usedBy: Partial<Record<string, string[]>>,
): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  for (const e of edges) {
    out[e.id] = Object.entries(usedBy)
      .filter(([, ids]) => ids?.includes(e.id))
      .map(([pipeline]) => pipeline);
  }
  return out;
}
