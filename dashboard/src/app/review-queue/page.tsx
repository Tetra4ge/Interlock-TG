import { Badge, Card, EmptyState, ErrorPanel, PageHeader } from "@/components/ui";
import { fetchReviewQueue } from "@/lib/api";
import { humanize } from "@/lib/format";

export default async function ReviewQueuePage() {
  const res = await fetchReviewQueue();
  if (!res.ok) {
    return (
      <>
        <PageHeader title="Review queue" />
        <ErrorPanel error={res.error} />
      </>
    );
  }
  const items = res.data;
  return (
    <>
      <PageHeader
        title="Review queue"
        subtitle={
          <>
            Extracted facts that failed a check and are waiting for a human decision. This page is read-only: decide with{" "}
            <code>uv run hl review</code>, which keeps the audit trail.
          </>
        }
      />
      {items.length === 0 ? (
        <EmptyState title="The review queue is empty">Nothing is waiting for a decision.</EmptyState>
      ) : (
        <div className="space-y-3">
          {items.map((i) => (
            <Card key={i.record_id}>
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <Badge tone="warn">{humanize(i.reason)}</Badge>
                <span className="font-medium">{humanize(i.record_type) || "record"}</span>
                <span className="text-muted">
                  {[i.company_id, i.fiscal_year].filter(Boolean).join(" · ")} · queued {i.created_at}
                </span>
                <span className="ml-auto font-mono text-xs text-muted">{i.record_id}</span>
              </div>
              <pre className="mt-2 max-h-48 overflow-auto rounded-md bg-surface-muted p-2 text-xs">{JSON.stringify(i.payload, null, 2)}</pre>
            </Card>
          ))}
        </div>
      )}
    </>
  );
}
