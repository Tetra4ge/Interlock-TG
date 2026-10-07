import Link from "next/link";
import AnswerCard from "@/components/AnswerCard";
import QuestionPicker from "@/components/QuestionPicker";
import RunSelector from "@/components/RunSelector";
import SubgraphCanvas from "@/components/SubgraphCanvas";
import TraceTable from "@/components/TraceTable";
import { Card, EmptyState, ErrorPanel, PageHeader, PipelineName } from "@/components/ui";
import { fetchCompareRuns, fetchQuestions, fetchResult, fetchRuns } from "@/lib/api";
import { edgeIdsOf } from "@/lib/evidence";
import { humanize } from "@/lib/format";
import { PIPELINES, PIPELINE_ORDER } from "@/lib/pipelines";
import { selectionFromParams } from "@/lib/runs";
import type { PipelineKey, ResultOut } from "@/lib/types";

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

function one(v: string | string[] | undefined): string | undefined {
  return Array.isArray(v) ? v[0] : v;
}

export default async function InspectorPage({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams;
  const runsRes = await fetchRuns();
  if (!runsRes.ok) {
    return (
      <>
        <PageHeader title="Question inspector" />
        <ErrorPanel error={runsRes.error} />
      </>
    );
  }
  const selection = selectionFromParams(params, runsRes.data, "dev");
  if (Object.keys(selection).length === 0) {
    return (
      <>
        <PageHeader title="Question inspector" />
        <EmptyState title="No evaluation runs yet" />
      </>
    );
  }
  const compareRes = await fetchCompareRuns(selection);
  if (!compareRes.ok) {
    return (
      <>
        <PageHeader title="Question inspector" />
        <ErrorPanel title="Could not compare these runs" error={compareRes.error} />
      </>
    );
  }
  const compare = compareRes.data;
  const wantedQid = one(params.q);
  const row = compare.questions.find((q) => q.qid === wantedQid) ?? compare.questions[0];
  const showGold = one(params.gold) === "1";

  const results: Partial<Record<PipelineKey, ResultOut | string>> = {};
  const gold = row && showGold ? await fetchQuestions(undefined, true) : null;
  if (row) {
    await Promise.all(
      PIPELINE_ORDER.map(async (key) => {
        const runId = compare.runs[key];
        if (!runId) return;
        const res = await fetchResult(runId, row.qid);
        results[key] = res.ok ? res.data : res.error;
      }),
    );
  }
  const goldQuestion = gold?.ok ? gold.data.find((q) => q.qid === row?.qid) : undefined;

  const baseQuery: Record<string, string> = {};
  for (const key of PIPELINE_ORDER) if (selection[key]) baseQuery[key] = selection[key]!;
  if (showGold) baseQuery.gold = "1";
  const goldToggle = new URLSearchParams({ ...baseQuery, ...(row ? { q: row.qid } : {}) });
  if (showGold) goldToggle.delete("gold");
  else goldToggle.set("gold", "1");

  const edgeIds: Partial<Record<PipelineKey, string[]>> = {};
  for (const key of PIPELINE_ORDER) {
    const r = results[key];
    if (r && typeof r !== "string") edgeIds[key] = edgeIdsOf(r.result);
  }

  return (
    <>
      <PageHeader
        title="Question inspector"
        subtitle="One question, three answers side by side: what each pipeline answered, what it cited, what it retrieved from the graph and every step it took."
      >
        <RunSelector runs={runsRes.data} selection={selection} basePath="/inspector" keep={{ ...(row ? { q: row.qid } : {}), ...(showGold ? { gold: "1" } : {}) }} />
      </PageHeader>

      {!row ? (
        <EmptyState title="The selected runs have no questions in common" />
      ) : (
        <div className="grid gap-6 lg:grid-cols-[20rem_1fr]">
          <aside>
            <QuestionPicker rows={compare.questions} selected={row.qid} basePath="/inspector" query={Object.fromEntries(Object.entries(baseQuery))} />
          </aside>

          <div className="min-w-0 space-y-6">
            <Card>
              <p className="text-xs text-muted">{row.qid} · {humanize(row.category)}</p>
              <h2 className="mt-1 text-lg font-semibold">{row.question}</h2>
              <div className="mt-3 flex flex-wrap items-center gap-3 text-sm">
                <Link href={`/inspector?${goldToggle.toString()}`} className="rounded-md border border-border px-2 py-1 text-xs font-medium hover:bg-surface-muted">
                  {showGold ? "Hide gold answer" : "Show gold answer"}
                </Link>
                {showGold ? (
                  goldQuestion ? (
                    <span>
                      Gold: <strong>{Array.isArray(goldQuestion.gold_answer) ? goldQuestion.gold_answer.join("; ") : String(goldQuestion.gold_answer ?? "(none: this question has no answer)")}</strong>
                    </span>
                  ) : (
                    <span className="text-muted">Gold answer not available.</span>
                  )
                ) : null}
              </div>
            </Card>

            <div className="grid gap-4 xl:grid-cols-3">
              {PIPELINE_ORDER.map((key) => {
                const r = results[key];
                if (!compare.runs[key]) {
                  return (
                    <Card key={key} title={PIPELINES[key].label}>
                      <p className="text-sm text-muted">No run selected for this pipeline.</p>
                    </Card>
                  );
                }
                if (!r || typeof r === "string") {
                  return (
                    <Card key={key} title={key}>
                      <PipelineName pipeline={key} />
                      <p className="mt-2 text-sm text-muted">{r ?? "No answer stored for this question."}</p>
                    </Card>
                  );
                }
                return <AnswerCard key={key} pipeline={key} result={r.result} score={r.score} />;
              })}
            </div>

            <Card title="Retrieved subgraph" note="The graph facts the answers used. Edges on the question's gold evidence pages are haloed when the gold answer is shown.">
              <SubgraphCanvas edgeIdsByPipeline={edgeIds} gold={showGold && goldQuestion ? goldQuestion.gold_evidence : null} />
            </Card>

            <Card title="Step-by-step traces" note="Retrieval, LLM turns, tool calls and verifier verdicts, with tokens, cost and time.">
              <div className="space-y-2">
                {PIPELINE_ORDER.map((key) => {
                  const r = results[key];
                  if (!r || typeof r === "string") return null;
                  return (
                    <details key={key} open={key === "agent"} className="rounded-lg border border-border p-3">
                      <summary className="cursor-pointer text-sm font-medium">
                        <PipelineName pipeline={key} /> <span className="font-normal text-muted">· {r.result.trace.length} steps</span>
                      </summary>
                      <div className="mt-3">
                        <TraceTable steps={r.result.trace} />
                      </div>
                    </details>
                  );
                })}
              </div>
            </Card>
          </div>
        </div>
      )}
    </>
  );
}
