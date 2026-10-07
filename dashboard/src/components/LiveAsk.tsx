"use client";

import { useEffect, useReducer, useRef } from "react";
import AnswerCard from "@/components/AnswerCard";
import { Badge, Card, ErrorPanel, PipelineName } from "@/components/ui";
import { compareQuestion } from "@/lib/api";
import { MAX_QUESTION_CHARS, checkQuestion, missingPipelines } from "@/lib/live";
import { PIPELINES, PIPELINE_ORDER } from "@/lib/pipelines";
import type { CompareOut, ExampleQuestion } from "@/lib/types";

type State =
  | { phase: "idle"; text: string; notice: string | null }
  | { phase: "running"; text: string; question: string }
  | { phase: "done"; text: string; question: string; out: CompareOut; seconds: number }
  | { phase: "error"; text: string; error: string; needsKey: boolean };

type Action =
  | { type: "edit"; text: string }
  | { type: "invalid"; error: string }
  | { type: "start"; question: string }
  | { type: "done"; out: CompareOut; seconds: number }
  | { type: "fail"; error: string; needsKey: boolean };

function reducer(state: State, a: Action): State {
  switch (a.type) {
    case "edit":
      return { phase: "idle", text: a.text, notice: null };
    case "invalid":
      return { phase: "idle", text: state.text, notice: a.error };
    case "start":
      return { phase: "running", text: state.text, question: a.question };
    case "done":
      return { phase: "done", text: state.text, question: state.phase === "running" ? state.question : "", out: a.out, seconds: a.seconds };
    case "fail":
      return { phase: "error", text: state.text, error: a.error, needsKey: a.needsKey };
  }
}

/** The request and its stopwatch live outside the component so rendering stays pure. */
async function timedCompare(question: string, signal: AbortSignal) {
  const started = Date.now();
  const res = await compareQuestion(question, signal);
  return { res, seconds: (Date.now() - started) / 1000 };
}

function Spinner({ label }: { label: string }) {
  return (
    <div role="status" aria-label={label} className="flex items-center gap-2 text-sm text-muted">
      <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-border border-t-foreground" />
      Working…
    </div>
  );
}

/** Ask one question and see all three pipelines answer it. Example questions are cached
 *  (instant, no cost); anything else needs an API key on the server. */
export default function LiveAsk({
  examples,
  demoMode,
  hasKey,
}: {
  examples: ExampleQuestion[];
  demoMode: boolean;
  hasKey: boolean;
}) {
  const [state, dispatch] = useReducer(reducer, { phase: "idle", text: "", notice: null } as State);
  const latest = useRef(0); // ignore a response that arrives after a newer question was asked
  const abort = useRef<AbortController | null>(null);
  useEffect(() => () => abort.current?.abort(), []);

  async function ask(text: string) {
    const check = checkQuestion(text);
    if (!check.ok) {
      dispatch({ type: "invalid", error: check.error });
      return;
    }
    abort.current?.abort();
    const controller = new AbortController();
    abort.current = controller;
    const id = ++latest.current;
    dispatch({ type: "start", question: check.question });

    const { res, seconds } = await timedCompare(check.question, controller.signal);
    if (id !== latest.current || controller.signal.aborted) return;
    if (res.ok) dispatch({ type: "done", out: res.data, seconds });
    else dispatch({ type: "fail", error: res.error, needsKey: res.status === 503 });
  }

  function pick(question: string) {
    dispatch({ type: "edit", text: question });
    void ask(question);
  }

  const running = state.phase === "running";
  const notice = state.phase === "idle" ? state.notice : null;

  return (
    <div className="space-y-6">
      {demoMode ? (
        <div role="note" className="rounded-lg border border-amber-300 bg-warn-bg px-3 py-2 text-sm text-warn-fg">
          {hasKey
            ? "Demo mode: example questions are answered instantly from stored results; other questions run live."
            : "Demo mode: no API key is configured, so only the example questions below can be answered."}
        </div>
      ) : null}

      <Card>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void ask(state.text);
          }}
          className="flex flex-col gap-2 sm:flex-row"
        >
          <label className="flex-1">
            <span className="sr-only">Your question</span>
            <input
              value={state.text}
              onChange={(e) => dispatch({ type: "edit", text: e.target.value })}
              placeholder="e.g. Who is the statutory auditor of Tata Motors in FY2023-24?"
              maxLength={MAX_QUESTION_CHARS * 2}
              className="w-full rounded-md border border-border bg-surface px-3 py-2 text-sm"
            />
          </label>
          <button type="submit" disabled={running || !state.text.trim()} className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-background disabled:opacity-50">
            {running ? "Asking…" : "Ask all three"}
          </button>
        </form>
        <p className="mt-1 text-xs text-muted">{state.text.trim().length}/{MAX_QUESTION_CHARS}</p>
        {notice ? <p role="alert" className="mt-1 text-sm text-danger">{notice}</p> : null}

        {examples.length > 0 ? (
          <div className="mt-3">
            <p className="mb-1 text-xs font-medium">Example questions {demoMode || !hasKey ? "(instant, cached)" : ""}</p>
            <div className="flex flex-wrap gap-2">
              {examples.map((ex) => (
                <button
                  key={ex.question}
                  onClick={() => pick(ex.question)}
                  disabled={running}
                  title={`Cached for: ${ex.pipelines.join(", ")}`}
                  className="rounded-full border border-border px-3 py-1 text-left text-xs hover:bg-surface-muted disabled:opacity-50"
                >
                  {ex.question}
                </button>
              ))}
            </div>
          </div>
        ) : null}
      </Card>

      {state.phase === "error" ? (
        <ErrorPanel
          title={state.needsKey ? "That question needs a live model" : "The question could not be answered"}
          error={state.error}
        />
      ) : null}

      {running ? (
        <div className="grid gap-4 xl:grid-cols-3" aria-busy="true">
          {PIPELINE_ORDER.map((k) => (
            <Card key={k}>
              <PipelineName pipeline={k} />
              <p className="mt-1 mb-3 text-xs text-muted">{PIPELINES[k].blurb}</p>
              <Spinner label={`${PIPELINES[k].label} is working`} />
            </Card>
          ))}
        </div>
      ) : null}

      {state.phase === "done" ? (
        <div className="space-y-3">
          <p className="text-sm text-muted">
            <strong className="text-foreground">{state.question}</strong> · answered in {state.seconds.toFixed(1)} s
            {state.out.cached ? <> · <Badge>Cached</Badge> stored results, no model call</> : null}
          </p>
          <div className="grid gap-4 xl:grid-cols-3">
            {PIPELINE_ORDER.map((k) => {
              const r = state.out.results[k];
              return r ? (
                <AnswerCard key={k} pipeline={k} result={r} cached={state.out.cached} />
              ) : (
                <Card key={k}>
                  <PipelineName pipeline={k} />
                  <p className="mt-2 text-sm text-muted">No stored answer for this pipeline.</p>
                </Card>
              );
            })}
          </div>
          {missingPipelines(state.out.results, PIPELINE_ORDER).length > 0 && state.out.cached ? (
            <p className="text-xs text-muted">Cached answers only cover pipelines that have a stored run.</p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
