import FailureChart from "@/components/FailureChart";
import FailureTable from "@/components/FailureTable";
import RunSelector from "@/components/RunSelector";
import { Card, EmptyState, ErrorPanel, PageHeader } from "@/components/ui";
import { fetchCompareRuns, fetchRuns } from "@/lib/api";
import { failureStack } from "@/lib/chart";
import { failureRows } from "@/lib/failures";
import { sampleCaveats, selectionFromParams, selectionQuery } from "@/lib/runs";

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

export default async function FailuresPage({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams;
  const runsRes = await fetchRuns();
  if (!runsRes.ok) {
    return (
      <>
        <PageHeader title="Failures" />
        <ErrorPanel error={runsRes.error} />
      </>
    );
  }
  const selection = selectionFromParams(params, runsRes.data, "dev");
  if (Object.keys(selection).length === 0) {
    return (
      <>
        <PageHeader title="Failures" />
        <EmptyState title="No evaluation runs yet" />
      </>
    );
  }
  const compareRes = await fetchCompareRuns(selection);

  return (
    <>
      <PageHeader
        title="How each pipeline fails"
        subtitle="Failure types per pipeline, assigned by a deterministic classifier (and the faithfulness judge). Click through to see the full answer and trace."
      >
        <RunSelector runs={runsRes.data} selection={selection} basePath="/failures" />
      </PageHeader>

      {!compareRes.ok ? (
        <ErrorPanel title="Could not compare these runs" error={compareRes.error} />
      ) : (
        (() => {
          const compare = compareRes.data;
          const stack = failureStack(compare.metrics);
          const rows = failureRows(compare);
          return (
            <div className="space-y-6">
              {sampleCaveats(compare.metrics).map((note) => (
                <div key={note} role="note" className="rounded-lg border border-amber-300 bg-warn-bg px-3 py-2 text-sm text-warn-fg">
                  {note}
                </div>
              ))}
              <Card title="Failure types" note="Number of questions each pipeline got wrong, by cause.">
                {stack.labels.length ? (
                  <FailureChart rows={stack.rows} labels={stack.labels} />
                ) : (
                  <p className="text-sm text-muted">No labelled failures in these runs.</p>
                )}
              </Card>
              <Card title="Failing questions" note="Every question a pipeline did not fully answer correctly.">
                <FailureTable rows={rows} selectionQuery={selectionQuery(selection)} />
              </Card>
            </div>
          );
        })()
      )}
    </>
  );
}
