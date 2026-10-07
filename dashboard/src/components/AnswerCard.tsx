"use client";

import { useMemo, useState } from "react";
import CitationDrawer from "@/components/CitationDrawer";
import { Badge, PipelineName } from "@/components/ui";
import { citationChips, splitMarkers } from "@/lib/evidence";
import { humanize, money, ms } from "@/lib/format";
import { PIPELINES } from "@/lib/pipelines";
import type { AnswerResult, PipelineKey, ScoreRow, Status } from "@/lib/types";

const STATUS_TONE: Record<Status, "ok" | "warn" | "bad" | "neutral"> = {
  ok: "ok",
  abstained: "neutral",
  budget_exceeded: "warn",
  error: "bad",
};

function Verdict({ score }: { score: ScoreRow | null }) {
  if (!score || score.correct === null) return null;
  if (score.correct >= 1) return <Badge tone="ok">Correct</Badge>;
  if (score.correct > 0) return <Badge tone="warn">Partly correct ({Math.round(score.correct * 100)}%)</Badge>;
  return <Badge tone="bad">Incorrect</Badge>;
}

/** One pipeline's answer: status, verdict, the answer with clickable [E#] citation
 *  chips, and what it cost. */
export default function AnswerCard({
  pipeline,
  result,
  score,
  cached = false,
}: {
  pipeline: PipelineKey;
  result: AnswerResult;
  score?: ScoreRow | null;
  cached?: boolean;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const chips = useMemo(() => citationChips(result), [result]);
  const parts = useMemo(() => splitMarkers(result.answer_long), [result.answer_long]);
  const u = result.usage;
  const color = PIPELINES[pipeline].color;

  const openLabel = open ?? "";
  const evidenceIndex = openLabel ? Number(openLabel.slice(1)) - 1 : -1;

  return (
    <article className="flex flex-col rounded-xl border border-border bg-surface p-4 shadow-sm" style={{ borderTopColor: color, borderTopWidth: 4 }}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <PipelineName pipeline={pipeline} />
        <div className="flex flex-wrap gap-1.5">
          <Badge tone={STATUS_TONE[result.status]}>{humanize(result.status)}</Badge>
          <Verdict score={score ?? null} />
          {score?.failure_label ? <Badge tone="bad">{humanize(score.failure_label)}</Badge> : null}
          {cached ? <Badge title="Stored answer, not a live run">Cached</Badge> : null}
        </div>
      </div>

      <p className="mt-3 text-lg font-semibold leading-snug" data-testid="answer-short">
        {result.answer_short || <span className="text-muted">(no answer)</span>}
      </p>

      {result.answer_long ? (
        <p className="mt-2 text-sm leading-relaxed">
          {parts.map((p, i) =>
            p.kind === "text" ? (
              <span key={i}>{p.value}</span>
            ) : (
              <span key={i} className="mx-0.5 inline-flex gap-0.5">
                {p.value.split(",").map((label) => {
                  const chip = chips.find((c) => c.label === label);
                  return (
                    <button
                      key={label}
                      onClick={() => setOpen(open === label ? null : label)}
                      aria-expanded={open === label}
                      className="rounded bg-surface-muted px-1 text-xs font-medium hover:underline"
                      style={{ color }}
                    >
                      {label}
                      {chip ? `, p.${chip.page}` : ""}
                    </button>
                  );
                })}
              </span>
            ),
          )}
        </p>
      ) : null}

      {result.status === "error" ? (
        <p role="alert" className="mt-2 text-xs text-danger">
          {result.trace.at(-1)?.error ?? "This pipeline failed."}
        </p>
      ) : null}

      {open ? (
        <CitationDrawer label={open} evidence={evidenceIndex >= 0 ? result.evidence[evidenceIndex] : undefined} chips={chips} onClose={() => setOpen(null)} />
      ) : null}

      {chips.length > 0 && !open ? (
        <p className="mt-3 text-xs text-muted">
          {chips.length} citation{chips.length === 1 ? "" : "s"}: click an [E#] marker to read the evidence.
        </p>
      ) : null}

      <dl className="mt-auto grid grid-cols-4 gap-2 border-t border-border pt-3 text-xs">
        <div><dt className="text-muted">Tokens</dt><dd className="tabular-nums">{u.tokens_in + u.tokens_out}</dd></div>
        <div><dt className="text-muted">Cost</dt><dd className="tabular-nums">{money(u.cost_usd)}</dd></div>
        <div><dt className="text-muted">Latency</dt><dd className="tabular-nums">{ms(u.latency_ms)}</dd></div>
        <div><dt className="text-muted">LLM / tool calls</dt><dd className="tabular-nums">{u.llm_calls} / {u.tool_calls}</dd></div>
      </dl>
      {score?.judge_reason ? <p className="mt-2 text-xs text-muted">Judge: {score.judge_reason}</p> : null}
    </article>
  );
}
