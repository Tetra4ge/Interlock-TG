import { Badge, Card, ErrorPanel, PageHeader, Stat } from "@/components/ui";
import { fetchDataQuality } from "@/lib/api";
import { humanize } from "@/lib/format";

function Breakdown({ title, data }: { title: string; data: Record<string, number> }) {
  const entries = Object.entries(data).sort((a, b) => b[1] - a[1]);
  return (
    <Card title={title}>
      {entries.length === 0 ? (
        <p className="text-sm text-muted">Nothing recorded.</p>
      ) : (
        <ul className="space-y-1 text-sm">
          {entries.map(([k, v]) => (
            <li key={k} className="flex justify-between">
              <span>{humanize(k)}</span>
              <span className="tabular-nums">{v}</span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

export default async function DataQualityPage() {
  const res = await fetchDataQuality();
  if (!res.ok) {
    return (
      <>
        <PageHeader title="Data quality" />
        <ErrorPanel error={res.error} />
      </>
    );
  }
  const q = res.data;
  const pct = q.provenance_complete_pct;
  return (
    <>
      <PageHeader title="Data quality" subtitle="What the answers are built on. Every figure is counted from the extraction store, not assumed." />
      <div className="space-y-6">
        <Card title="Corpus" note={q.note}>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            <Stat label="Documents" value={q.documents} hint={`${q.documents_parsed} parsed, ${q.documents_failed} failed`} />
            <Stat label="Companies with facts" value={q.companies} />
            <Stat label="Facts extracted" value={q.records_total} hint={`${q.records_accepted} accepted, ${q.records_rejected} rejected`} />
            <Stat label="Awaiting review" value={q.review_queue} />
          </div>
        </Card>

        <Card title="Provenance" note="A fact with a quoted source page can be cited and checked; one without cannot.">
          <div className="flex items-center gap-4">
            <div className="text-3xl font-semibold tabular-nums">{pct === null ? "–" : `${pct}%`}</div>
            <div className="text-sm">
              of accepted facts carry a verbatim quote and page
              {pct !== null && pct < 100 ? <Badge tone="warn">below 100%</Badge> : null}
            </div>
          </div>
          {pct !== null ? (
            <div className="mt-3 h-2 w-full overflow-hidden rounded-full bg-surface-muted" role="img" aria-label={`${pct}% of accepted facts have a quoted source page`}>
              <div className="h-full bg-ok" style={{ width: `${pct}%` }} />
            </div>
          ) : null}
        </Card>

        <div className="grid gap-4 md:grid-cols-2">
          <Breakdown title="Entities by kind" data={q.entities_by_kind} />
          <Breakdown title="How mentions were resolved" data={q.mentions_by_method} />
        </div>
      </div>
    </>
  );
}
