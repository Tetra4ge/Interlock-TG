import { Badge } from "@/components/ui";
import { money, ms } from "@/lib/format";
import type { TraceStep } from "@/lib/types";

const KIND_TONE: Record<string, "neutral" | "ok" | "warn" | "bad"> = {
  llm: "warn",
  tool: "ok",
  retrieve: "neutral",
  verify: "neutral",
};

/** Step-by-step record of what a pipeline did: retrieval, LLM turns, tool calls and
 *  verifier verdicts, with tokens, cost, latency and any error. */
export default function TraceTable({ steps }: { steps: TraceStep[] }) {
  if (steps.length === 0) return <p className="text-sm text-muted">No trace recorded.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead className="text-left text-muted">
          <tr>
            <th className="pb-1 pr-2">#</th><th className="pr-2">Kind</th><th className="pr-2">Step</th>
            <th className="pr-2">Input</th><th className="pr-2">Output</th>
            <th className="pr-2 text-right">Tokens</th><th className="pr-2 text-right">Cost</th><th className="text-right">Time</th>
          </tr>
        </thead>
        <tbody>
          {steps.map((s) => (
            <tr key={s.step} className="border-t border-border align-top">
              <td className="py-1 pr-2 tabular-nums">{s.step}</td>
              <td className="pr-2"><Badge tone={s.error ? "bad" : (KIND_TONE[s.kind] ?? "neutral")}>{s.kind}</Badge></td>
              <td className="pr-2 font-medium">{s.name}</td>
              <td className="max-w-56 break-words pr-2 text-muted">{s.input_summary || "–"}</td>
              <td className="max-w-72 break-words pr-2">
                {s.error ? <span className="text-danger">{s.error}</span> : s.output_summary || "–"}
              </td>
              <td className="pr-2 text-right tabular-nums">{s.tokens_in || s.tokens_out ? `${s.tokens_in}→${s.tokens_out}` : "–"}</td>
              <td className="pr-2 text-right tabular-nums">{s.cost_usd ? money(s.cost_usd) : "–"}</td>
              <td className="text-right tabular-nums">{s.latency_ms ? ms(s.latency_ms) : "–"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
