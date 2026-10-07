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
    <header className="mb-8 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">{title}</h1>
        {subtitle ? (
          <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-muted-fg">{subtitle}</p>
        ) : null}
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
  accent = false,
}: {
  title?: string;
  note?: ReactNode;
  children: ReactNode;
  className?: string;
  accent?: boolean;
}) {
  return (
    <section
      className={[
        "rounded-xl border bg-surface-raised p-5 shadow-sm",
        accent ? "border-accent/30" : "border-border",
        className,
      ].join(" ")}
    >
      {title ? (
        <h2 className="mb-0.5 text-sm font-semibold text-foreground">{title}</h2>
      ) : null}
      {note ? (
        <p className="mb-4 text-xs leading-relaxed text-muted-fg">{note}</p>
      ) : title ? (
        <div className="mb-4" />
      ) : null}
      {children}
    </section>
  );
}

export function PipelineDot({ pipeline }: { pipeline: PipelineKey }) {
  return (
    <span
      aria-hidden
      className="inline-block h-2 w-2 rounded-full flex-shrink-0"
      style={{ backgroundColor: PIPELINES[pipeline].color }}
    />
  );
}

export function PipelineName({ pipeline }: { pipeline: PipelineKey }) {
  return (
    <span className="inline-flex items-center gap-1.5 font-medium text-foreground">
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
    <div className="flex flex-col gap-0.5">
      <div className="text-[10px] font-medium uppercase tracking-widest text-muted">{label}</div>
      <div className="text-xl font-semibold tabular-nums text-foreground">{value}</div>
      {hint ? <div className="text-xs text-muted-fg">{hint}</div> : null}
    </div>
  );
}

const TONES = {
  neutral: "bg-surface-muted text-muted-fg border border-border",
  ok:      "bg-ok-dim text-ok border border-ok/20",
  warn:    "bg-warn-bg text-warn-fg border border-warn/20",
  bad:     "bg-danger-dim text-danger border border-danger/20",
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
    <div className="rounded-xl border border-dashed border-border/60 bg-surface p-10 text-center">
      <p className="font-medium text-foreground">{title}</p>
      {children ? (
        <div className="mt-2 text-sm text-muted-fg">{children}</div>
      ) : null}
    </div>
  );
}

export function ErrorPanel({
  title = "Could not load data",
  error,
}: {
  title?: string;
  error: string;
}) {
  return (
    <div
      role="alert"
      className="rounded-xl border border-danger/30 bg-danger-dim p-4 text-sm"
    >
      <p className="font-semibold text-danger">{title}</p>
      <p className="mt-1 text-foreground/80">{error}</p>
    </div>
  );
}

export function Divider({ className = "" }: { className?: string }) {
  return <hr className={`border-border ${className}`} />;
}

export function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <p className="mb-3 text-[10px] font-semibold uppercase tracking-widest text-muted">
      {children}
    </p>
  );
}
