import CIBarsChart from "@/components/CIBarsChart";
import RunSelector from "@/components/RunSelector";
import { Badge, Card, EmptyState, ErrorPanel, PageHeader, PipelineName, Stat } from "@/components/ui";
import { fetchCompareRuns, fetchDataQuality, fetchRuns } from "@/lib/api";
import { accuracyRows } from "@/lib/chart";
import { humanize, money, ms, pct, pctRange, signed } from "@/lib/format";
import { PIPELINES, PIPELINE_ORDER } from "@/lib/pipelines";
import { sampleCaveats, selectionFromParams } from "@/lib/runs";
import type { PipelineKey } from "@/lib/types";

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

export default async function OverviewPage({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams;
  const runsRes = await fetchRuns();
  if (!runsRes.ok) {
    return (
      <>
        <PageHeader title="Overview" />
        <ErrorPanel error={runsRes.error} />
      </>
    );
  }
  const runs = runsRes.data;
  const selection = selectionFromParams(params, runs, "dev");
  if (Object.keys(selection).length === 0) {
    return (
      <>
        <PageHeader title="Overview" />
        <EmptyState title="No evaluation runs yet">
          Run <code>uv run hl eval --pipeline rag --split dev</code> and refresh.
        </EmptyState>
      </>
    );
  }

  const [compareRes, qualityRes] = await Promise.all([fetchCompareRuns(selection), fetchDataQuality()]);
  const compare = compareRes.ok ? compareRes.data : null;
  const present = PIPELINE_ORDER.filter((k) => compare?.metrics[k]);

  return (
    <>
      <PageHeader
        title="Who wins where?"
        subtitle="Accuracy per question category for each pipeline, scored against verified gold answers. Bars show the 95% bootstrap confidence interval."
      >
        <RunSelector runs={runs} selection={selection} basePath="/" />
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

          <div className="grid gap-4 md:grid-cols-3">
            {PIPELINE_ORDER.map((key) => {
              const m = compare.metrics[key];
              return (
                <Card key={key} title={PIPELINES[key].label} note={m ? `${m.run_id} · ${m.split} · n=${m.overall.n}` : PIPELINES[key].blurb}>
                  {m ? (
                    <div className="grid grid-cols-3 gap-2">
                      <Stat label="Accuracy" value={pct(m.overall.correct_mean)} hint={`95% CI ${pctRange(m.overall.correct_ci95)}`} />
                      <Stat label="Cost / q" value={money(m.overall.cost_usd_mean)} />
                      <Stat label="Median latency" value={ms(m.overall.latency_median_ms)} />
                    </div>
                  ) : (
                    <p className="text-sm text-muted">No run selected for this pipeline.</p>
                  )}
                </Card>
              );
            })}
          </div>

          <Card
            title="Accuracy by category"
            note={`Fraction of questions answered correctly, with 95% confidence intervals. Runs: ${present
              .map((k) => `${PIPELINES[k].short}=${compare.runs[k]}`)
              .join(", ")}.`}
          >
            <CIBarsChart rows={accuracyRows(compare.metrics)} pipelines={present} />
          </Card>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="Where each wins" note="The pipeline with the highest mean per category. A lead is clear only if the paired-difference interval excludes 0.">
              <table className="w-full text-sm">
                <thead className="text-left text-xs text-muted">
                  <tr><th className="pb-1">Category</th><th>Leader</th><th>Mean</th><th>Lead</th></tr>
                </thead>
                <tbody>
                  {Object.entries(compare.leaders).map(([cat, l]) => (
                    <tr key={cat} className="border-t border-border align-top">
                      <td className="py-1.5">{humanize(cat)}</td>
                      <td>
                        {l.pipeline ? (
                          <PipelineName pipeline={l.pipeline} />
                        ) : l.tied.length ? (
                          <span className="text-muted">tie: {l.tied.map((k: PipelineKey) => PIPELINES[k].short).join(", ")}</span>
                        ) : (
                          <span className="text-muted">–</span>
                        )}
                      </td>
                      <td className="tabular-nums">{pct(l.mean)}</td>
                      <td>
                        {l.pipeline ? (
                          <Badge tone={l.clear ? "ok" : "warn"} title={l.reason}>
                            {l.clear ? "clear" : "unclear"}
                          </Badge>
                        ) : null}
                        <div className="mt-0.5 max-w-60 text-xs text-muted">{l.reason}</div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>

            <Card title="Paired differences" note="Accuracy of A minus B on the questions both runs scored; positive means A is better.">
              {compare.pairs.length === 0 ? (
                <p className="text-sm text-muted">Select runs for at least two pipelines to compare them.</p>
              ) : (
                <table className="w-full text-sm">
                  <thead className="text-left text-xs text-muted">
                    <tr><th className="pb-1">A vs B</th><th>Pairs</th><th>A − B</th><th>95% CI</th><th>Verdict</th></tr>
                  </thead>
                  <tbody>
                    {compare.pairs.map((p) => (
                      <tr key={`${p.a}-${p.b}`} className="border-t border-border">
                        <td className="py-1.5">{PIPELINES[p.a].short} vs {PIPELINES[p.b].short}</td>
                        <td className="tabular-nums">{p.overall.n}</td>
                        <td className="tabular-nums">{signed(p.overall.diff)}</td>
                        <td className="tabular-nums">{p.overall.ci95 ? `${signed(p.overall.ci95[0])} to ${signed(p.overall.ci95[1])}` : "–"}</td>
                        <td>
                          <Badge tone={p.overall.verdict === "A better" ? "ok" : p.overall.verdict === "B better" ? "bad" : "neutral"}>
                            {p.overall.verdict}
                          </Badge>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Card>
          </div>

          <Card title="Data behind the answers" note="Measured from the local extraction store.">
            {qualityRes.ok ? (
              <div className="grid grid-cols-2 gap-4 md:grid-cols-5">
                <Stat label="Documents" value={qualityRes.data.documents} hint={`${qualityRes.data.documents_parsed} parsed`} />
                <Stat label="Companies" value={qualityRes.data.companies} />
                <Stat label="Accepted facts" value={qualityRes.data.records_accepted} hint={`of ${qualityRes.data.records_total} extracted`} />
                <Stat label="Entities" value={Object.values(qualityRes.data.entities_by_kind).reduce((a, b) => a + b, 0)} />
                <Stat
                  label="With a quoted source page"
                  value={qualityRes.data.provenance_complete_pct === null ? "–" : `${qualityRes.data.provenance_complete_pct}%`}
                  hint="measured, not assumed"
                />
              </div>
            ) : (
              <ErrorPanel title="Data quality unavailable" error={qualityRes.error} />
            )}
          </Card>
        </div>
      )}
    </>
  );
}
