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

  const evidenceIndex = open && /^E\d+$/.test(open) ? Number(open.slice(1)) - 1 : -1;

  return (
    <article
      className="flex flex-col rounded-xl border border-border bg-surface-raised overflow-hidden shadow-sm"
      style={{ borderTopColor: color, borderTopWidth: "3px" }}
    >
      {/* Header row */}
      <div className="flex flex-wrap items-center justify-between gap-2 px-4 pt-4 pb-3">
        <PipelineName pipeline={pipeline} />
        <div className="flex flex-wrap gap-1.5">
          <Badge tone={STATUS_TONE[result.status]}>{humanize(result.status)}</Badge>
          <Verdict score={score ?? null} />
          {score?.failure_label ? (
            <Badge tone="bad">{humanize(score.failure_label)}</Badge>
          ) : null}
          {cached ? (
            <Badge title="Stored answer, not a live run">Cached</Badge>
          ) : null}
        </div>
      </div>

      {/* Answer body */}
      <div className="px-4 pb-4 flex-1 flex flex-col gap-3">
        <p className="text-base font-semibold leading-snug text-foreground" data-testid="answer-short">
          {result.answer_short || <span className="text-muted">(no answer)</span>}
        </p>

        {result.answer_long ? (
          <p className="text-sm leading-relaxed text-foreground/80">
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
                        className="rounded bg-surface-muted px-1 text-xs font-medium hover:underline transition-colors"
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
          <p role="alert" className="text-xs text-danger">
            {result.trace.at(-1)?.error ?? "This pipeline failed."}
          </p>
        ) : null}

        {open ? (
          <CitationDrawer
            label={open}
            evidence={evidenceIndex >= 0 ? result.evidence[evidenceIndex] : undefined}
            chips={chips}
            onClose={() => setOpen(null)}
          />
        ) : null}

        {chips.length > 0 ? (
          <div>
            <p className="mb-1.5 text-[10px] font-medium uppercase tracking-widest text-muted">
              {chips.length} citation{chips.length === 1 ? "" : "s"}
            </p>
            <div className="flex flex-wrap gap-1.5">
              {chips.map((c, i) => {
                const key = c.label ?? `cite:${i}`;
                return (
                  <button
                    key={`${c.doc_id}-${c.page}-${i}`}
                    onClick={() => setOpen(open === key ? null : key)}
                    aria-expanded={open === key}
                    aria-label={`Citation ${i + 1}${c.label ? `, evidence ${c.label}` : ""}, page ${c.page}`}
                    className="rounded-md border border-border bg-surface-muted px-2 py-0.5 text-xs font-medium transition-colors hover:border-accent/40 hover:bg-accent-dim"
                    style={{ color }}
                  >
                    {c.label ? `${c.label} · ` : ""}p.{c.page}
                  </button>
                );
              })}
            </div>
          </div>
        ) : null}
      </div>

      {/* Footer stats */}
      <dl className="grid grid-cols-4 gap-2 border-t border-border bg-surface px-4 py-2.5 text-xs">
        <div>
          <dt className="text-muted">Tokens</dt>
          <dd className="tabular-nums text-muted-fg">{u.tokens_in + u.tokens_out}</dd>
        </div>
        <div>
          <dt className="text-muted">Cost</dt>
          <dd className="tabular-nums text-muted-fg">{money(u.cost_usd)}</dd>
        </div>
        <div>
          <dt className="text-muted">Latency</dt>
          <dd className="tabular-nums text-muted-fg">{ms(u.latency_ms)}</dd>
        </div>
        <div>
          <dt className="text-muted">LLM / tools</dt>
          <dd className="tabular-nums text-muted-fg">{u.llm_calls} / {u.tool_calls}</dd>
        </div>
      </dl>

      {score?.judge_reason ? (
        <p className="border-t border-border bg-surface px-4 py-2 text-xs text-muted-fg">
          Judge: {score.judge_reason}
        </p>
      ) : null}
    </article>
  );
}
