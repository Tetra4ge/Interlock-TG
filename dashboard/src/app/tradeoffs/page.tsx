import CallsChart from "@/components/CallsChart";
import RunSelector from "@/components/RunSelector";
import TradeoffScatter from "@/components/TradeoffScatter";
import { Card, EmptyState, ErrorPanel, PageHeader } from "@/components/ui";
import { fetchCompareRuns, fetchRuns } from "@/lib/api";
import { allZero, callsRows, takeaways, tradeoffPoints } from "@/lib/chart";
import { sampleCaveats, selectionFromParams } from "@/lib/runs";

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

export default async function TradeoffsPage({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams;
  const runsRes = await fetchRuns();
  if (!runsRes.ok) {
    return (
      <>
        <PageHeader title="Trade-offs" />
        <ErrorPanel error={runsRes.error} />
      </>
    );
  }
  const selection = selectionFromParams(params, runsRes.data, "dev");
  if (Object.keys(selection).length === 0) {
    return (
      <>
        <PageHeader title="Trade-offs" />
        <EmptyState title="No evaluation runs yet" />
      </>
    );
  }
  const compareRes = await fetchCompareRuns(selection);
  const compare = compareRes.ok ? compareRes.data : null;

  const costPoints = compare ? tradeoffPoints(compare.metrics, "cost") : [];
  const latencyPoints = compare ? tradeoffPoints(compare.metrics, "latency") : [];

  return (
    <>
      <PageHeader
        title="Cost, latency and accuracy"
        subtitle="What each pipeline spends to get its accuracy. Each point is one pipeline on one question category; larger points cover more questions."
      >
        <RunSelector runs={runsRes.data} selection={selection} basePath="/tradeoffs" />
      </PageHeader>

      {!compare ? (
        <ErrorPanel title="Could not compare these runs" error={compareRes.ok ? "" : compareRes.error} />
      ) : (
        <div className="space-y-6">
          {sampleCaveats(compare.metrics).map((note) => (
            <div key={note} role="note" className="rounded-lg border border-amber-300 bg-warn-bg px-3 py-2 text-sm text-warn-fg">
              {note}
            </div>
          ))}

          <Card title="Takeaways" note="Measured against the RAG baseline; accuracy claims follow the paired-difference interval.">
            <ul className="list-disc space-y-1 pl-5 text-sm">
              {takeaways(compare).map((t) => (
                <li key={t}>{t}</li>
              ))}
            </ul>
          </Card>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card
              title="Cost vs accuracy"
              note={
                allZero(costPoints)
                  ? "Every call here is priced at $0 (Groq free tier), so cost does not separate the pipelines. Use latency and call counts."
                  : "Mean dollars per question against accuracy."
              }
            >
              {costPoints.length ? (
                <TradeoffScatter points={costPoints} xName="Cost per question" xUnit=" $" label="Scatter chart of cost per question against accuracy" />
              ) : (
                <p className="text-sm text-muted">No cost data.</p>
              )}
            </Card>
            <Card title="Latency vs accuracy" note="Median seconds per question against accuracy.">
              {latencyPoints.length ? (
                <TradeoffScatter points={latencyPoints} xName="Median latency" xUnit=" s" label="Scatter chart of median latency against accuracy" />
              ) : (
                <p className="text-sm text-muted">No latency data.</p>
              )}
            </Card>
          </div>

          <Card title="Calls per question" note="Average LLM calls and tool calls. The agent's tool calls are graph and text lookups; RAG makes none.">
            <CallsChart rows={callsRows(compare.metrics)} />
          </Card>
        </div>
      )}
    </>
  );
}
