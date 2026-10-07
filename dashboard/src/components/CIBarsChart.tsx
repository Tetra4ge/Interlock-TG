"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  ErrorBar,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { AccuracyRow } from "@/lib/chart";
import { humanize, pct } from "@/lib/format";
import { PIPELINES } from "@/lib/pipelines";
import type { PipelineKey } from "@/lib/types";

interface TipProps {
  active?: boolean;
  payload?: { payload: AccuracyRow }[];
  label?: string;
  pipelines: PipelineKey[];
}

function Tip({ active, payload, label, pipelines }: TipProps) {
  if (!active || !payload?.length) return null;
  const row = payload[0].payload;
  return (
    <div className="rounded-lg border border-border bg-surface p-3 text-xs shadow-md">
      <p className="mb-1 font-semibold">
        {humanize(String(label))} <span className="font-normal text-muted">(n={row.n})</span>
      </p>
      {pipelines.map((k) => {
        const mean = row[k] as number | null;
        const err = row[`${k}_err`] as [number, number] | null;
        return (
          <p key={k} style={{ color: PIPELINES[k].color }}>
            {PIPELINES[k].label}: {pct(mean)}
            {mean !== null && err ? ` (95% CI ${pct(mean - err[0])}–${pct(mean + err[1])})` : ""}
          </p>
        );
      })}
    </div>
  );
}

/** Grouped bars of accuracy per category, with each bar's 95% confidence interval. */
export default function CIBarsChart({
  rows,
  pipelines,
}: {
  rows: AccuracyRow[];
  pipelines: PipelineKey[];
}) {
  return (
    <div role="img" aria-label="Grouped bar chart of accuracy by question category with 95% confidence intervals" className="h-80 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="category" tickFormatter={(c: string) => humanize(c)} />
          <YAxis domain={[0, 1]} tickFormatter={(v: number) => pct(v)} width={48} />
          <Tooltip content={<Tip pipelines={pipelines} />} cursor={{ fill: "rgba(148,163,184,0.15)" }} />
          <Legend formatter={(value: string) => PIPELINES[value as PipelineKey]?.label ?? value} />
          {pipelines.map((k) => (
            <Bar key={k} dataKey={k} name={k} fill={PIPELINES[k].color} isAnimationActive={false}>
              <ErrorBar dataKey={`${k}_err`} width={5} stroke="currentColor" strokeWidth={1.5} />
            </Bar>
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
