"use client";

import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { humanize } from "@/lib/format";
import { labelColor } from "@/lib/failures";
import { PIPELINES } from "@/lib/pipelines";
import type { PipelineKey } from "@/lib/types";

/** One bar per pipeline, stacked by failure label (counts of questions). */
export default function FailureChart({
  rows,
  labels,
}: {
  rows: Record<string, number | string>[];
  labels: string[];
}) {
  const data = rows.map((r) => ({ ...r, name: PIPELINES[r.pipeline as PipelineKey]?.label ?? String(r.pipeline) }));
  return (
    <div role="img" aria-label="Stacked bar chart of failure types for each pipeline" className="h-80 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="name" />
          <YAxis allowDecimals={false} width={32} />
          <Tooltip />
          <Legend formatter={(v: string) => humanize(v)} />
          {labels.map((l) => (
            <Bar key={l} dataKey={l} name={l} stackId="failures" fill={labelColor(l, labels)} isAnimationActive={false} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
