"use client";

import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { PIPELINES } from "@/lib/pipelines";
import type { PipelineKey } from "@/lib/types";

/** Mean LLM calls and tool calls per question, per pipeline. */
export default function CallsChart({
  rows,
}: {
  rows: { pipeline: string; llm: number; tool: number }[];
}) {
  const data = rows.map((r) => ({ ...r, name: PIPELINES[r.pipeline as PipelineKey]?.label ?? r.pipeline }));
  return (
    <div role="img" aria-label="Bar chart of average LLM calls and tool calls per question for each pipeline" className="h-72 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="name" />
          <YAxis allowDecimals width={40} />
          <Tooltip formatter={(v) => Number(v).toFixed(1)} />
          <Legend />
          <Bar dataKey="llm" name="LLM calls / question" fill="#64748b" isAnimationActive={false} />
          <Bar dataKey="tool" name="Tool calls / question" fill="#f59e0b" isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
