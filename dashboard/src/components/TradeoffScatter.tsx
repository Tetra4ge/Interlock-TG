"use client";

import {
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import type { ScatterPoint } from "@/lib/chart";
import { humanize } from "@/lib/format";
import { PIPELINES, PIPELINE_ORDER } from "@/lib/pipelines";

interface TipProps {
  active?: boolean;
  payload?: { payload: ScatterPoint }[];
  xName: string;
  xUnit: string;
}

function Tip({ active, payload, xName, xUnit }: TipProps) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return (
    <div className="rounded-lg border border-border bg-surface p-3 text-xs shadow-md">
      <p className="font-semibold" style={{ color: PIPELINES[p.pipeline].color }}>
        {PIPELINES[p.pipeline].label} · {humanize(p.label)}
      </p>
      <p>Accuracy: {p.y.toFixed(0)}% (n={p.n})</p>
      <p>
        {xName}: {p.x.toFixed(p.x < 1 ? 4 : 1)}
        {xUnit}
      </p>
    </div>
  );
}

/** Accuracy (y) against a cost axis (x), one series per pipeline, one point per category. */
export default function TradeoffScatter({
  points,
  xName,
  xUnit,
  label,
}: {
  points: ScatterPoint[];
  xName: string;
  xUnit: string;
  label: string;
}) {
  return (
    <div role="img" aria-label={label} className="h-72 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <ScatterChart margin={{ top: 8, right: 16, left: 0, bottom: 24 }}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis
            type="number"
            dataKey="x"
            name={xName}
            unit={xUnit}
            label={{ value: `${xName} (${xUnit.trim() || "$"})`, position: "insideBottom", offset: -12, fontSize: 12 }}
          />
          <YAxis type="number" dataKey="y" name="Accuracy" unit="%" domain={[0, 100]} width={48} />
          <ZAxis type="number" dataKey="n" range={[60, 260]} />
          <Tooltip content={<Tip xName={xName} xUnit={xUnit} />} cursor={{ strokeDasharray: "3 3" }} />
          <Legend formatter={(v: string) => PIPELINES[v as keyof typeof PIPELINES]?.label ?? v} />
          {PIPELINE_ORDER.map((k) => (
            <Scatter
              key={k}
              name={k}
              data={points.filter((p) => p.pipeline === k)}
              fill={PIPELINES[k].color}
              isAnimationActive={false}
            />
          ))}
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}
