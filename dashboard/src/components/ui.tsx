import type { ReactNode } from "react";
import { PIPELINES } from "@/lib/pipelines";
import type { PipelineKey } from "@/lib/types";

export function PageHeader({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {subtitle ? <p className="mt-1 max-w-3xl text-sm text-muted">{subtitle}</p> : null}
      </div>
      {children}
    </header>
  );
}

export function Card({
  title,
  note,
  children,
  className = "",
}: {
  title?: string;
  note?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded-xl border border-border bg-surface p-4 shadow-sm ${className}`}>
      {title ? <h2 className="text-sm font-semibold">{title}</h2> : null}
      {note ? <p className="mt-0.5 mb-3 text-xs text-muted">{note}</p> : <div className="mb-3" />}
      {children}
    </section>
  );
}

export function PipelineDot({ pipeline }: { pipeline: PipelineKey }) {
  return (
    <span
      aria-hidden
      className="inline-block h-2.5 w-2.5 rounded-full"
      style={{ backgroundColor: PIPELINES[pipeline].color }}
    />
  );
}

export function PipelineName({ pipeline }: { pipeline: PipelineKey }) {
  return (
    <span className="inline-flex items-center gap-1.5 font-medium">
      <PipelineDot pipeline={pipeline} />
      {PIPELINES[pipeline].label}
    </span>
  );
}

export function Stat({
  label,
  value,
  hint,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
}) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-muted">{label}</div>
      <div className="text-xl font-semibold tabular-nums">{value}</div>
      {hint ? <div className="text-xs text-muted">{hint}</div> : null}
    </div>
  );
}

const TONES = {
  neutral: "bg-surface-muted text-foreground",
  ok: "bg-emerald-100 text-emerald-900 dark:bg-emerald-900/40 dark:text-emerald-200",
  warn: "bg-amber-100 text-amber-900 dark:bg-amber-900/40 dark:text-amber-200",
  bad: "bg-red-100 text-red-900 dark:bg-red-900/40 dark:text-red-200",
} as const;

export function Badge({
  tone = "neutral",
  children,
  title,
}: {
  tone?: keyof typeof TONES;
  children: ReactNode;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${TONES[tone]}`}
    >
      {children}
    </span>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-border p-8 text-center">
      <p className="font-medium">{title}</p>
      {children ? <div className="mt-1 text-sm text-muted">{children}</div> : null}
    </div>
  );
}

/** Shown when an API call fails, instead of crashing the page. */
export function ErrorPanel({ title = "Could not load data", error }: { title?: string; error: string }) {
  return (
    <div role="alert" className="rounded-xl border border-red-300 bg-red-50 p-4 text-sm dark:border-red-900 dark:bg-red-950/40">
      <p className="font-semibold text-danger">{title}</p>
      <p className="mt-1 text-foreground">{error}</p>
    </div>
  );
}
