import Link from "next/link";

function Tag({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center rounded-full border border-accent/30 bg-accent-dim px-2.5 py-0.5 text-xs font-medium text-accent">
      {children}
    </span>
  );
}

function SectionHeading({ label, title, subtitle }: { label: string; title: string; subtitle?: string }) {
  return (
    <div className="mb-10 text-center">
      <p className="mb-2 text-xs font-semibold uppercase tracking-widest text-accent">{label}</p>
      <h2 className="text-3xl font-semibold tracking-tight text-foreground">{title}</h2>
      {subtitle ? <p className="mx-auto mt-3 max-w-2xl text-sm leading-relaxed text-muted-fg">{subtitle}</p> : null}
    </div>
  );
}

function PipelineCard({
  icon,
  name,
  color,
  how,
  best,
  cost,
}: {
  icon: string;
  name: string;
  color: string;
  how: string;
  best: string;
  cost: string;
}) {
  return (
    <div
      className="flex flex-col gap-3 rounded-xl border border-border bg-surface-raised p-5"
      style={{ borderTopColor: color, borderTopWidth: 3 }}
    >
      <div className="flex items-center gap-2">
        <span className="text-xl">{icon}</span>
        <span className="font-semibold text-foreground">{name}</span>
      </div>
      <p className="text-sm leading-relaxed text-muted-fg">{how}</p>
      <div className="mt-auto flex flex-col gap-1.5 border-t border-border pt-3 text-xs">
        <div>
          <span className="font-medium text-muted">Best for: </span>
          <span className="text-muted-fg">{best}</span>
        </div>
        <div>
          <span className="font-medium text-muted">LLM cost: </span>
          <span className="text-muted-fg">{cost}</span>
        </div>
      </div>
    </div>
  );
}

function StatBox({ value, label, sub }: { value: string; label: string; sub?: string }) {
  return (
    <div className="rounded-xl border border-border bg-surface-raised p-5 text-center">
      <p className="text-3xl font-semibold tabular-nums text-accent">{value}</p>
      <p className="mt-1 text-sm font-medium text-foreground">{label}</p>
      {sub ? <p className="mt-0.5 text-xs text-muted-fg">{sub}</p> : null}
    </div>
  );
}

function ProblemPoint({ icon, title, body }: { icon: string; title: string; body: string }) {
  return (
    <div className="flex gap-4">
      <div className="mt-0.5 flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg border border-border bg-surface-muted text-base">
        {icon}
      </div>
      <div>
        <p className="font-medium text-foreground">{title}</p>
        <p className="mt-0.5 text-sm leading-relaxed text-muted-fg">{body}</p>
      </div>
    </div>
  );
}

function GraphNode({ label, sub, accent = false }: { label: string; sub?: string; accent?: boolean }) {
  return (
    <div
      className={`rounded-lg border px-3 py-2 text-center text-xs ${
        accent
          ? "border-accent/50 bg-accent-dim text-accent"
          : "border-border bg-surface-muted text-muted-fg"
      }`}
    >
      <p className="font-semibold">{label}</p>
      {sub ? <p className="mt-0.5 opacity-70">{sub}</p> : null}
    </div>
  );
}

export default function LandingPage() {
  return (
    <div className="space-y-24 pb-16">

      {/* ── Hero ──────────────────────────────────────────────────────────── */}
      <section className="relative pt-8 text-center">
        <div
          aria-hidden
          className="pointer-events-none absolute inset-x-0 top-0 mx-auto h-72 w-72 rounded-full opacity-10 blur-3xl"
          style={{ background: "radial-gradient(circle, #f59e0b 0%, transparent 70%)" }}
        />

        <div className="relative flex flex-wrap justify-center gap-2 mb-6">
          <Tag>TigerGraph Hackathon</Tag>
          <Tag>Indian Corporate Governance</Tag>
          <Tag>Agentic GraphRAG</Tag>
        </div>

        <h1 className="mx-auto max-w-3xl text-4xl font-semibold tracking-tight text-foreground sm:text-5xl">
          When the answer lives{" "}
          <span className="text-accent">across documents</span>,<br />
          vector search is not enough.
        </h1>

        <p className="mx-auto mt-6 max-w-2xl text-base leading-relaxed text-muted-fg">
          <strong className="text-foreground">Interlock</strong> extracts board-interlocks, audit
          relationships, related-party transaction trails and promoter-pledge chains from NSE/BSE
          annual reports — loads them into a TigerGraph knowledge graph — then runs RAG,
          GraphRAG and Agentic GraphRAG side by side on the same questions so you can see exactly
          where the graph changes the answer.
        </p>

        <div className="mt-10 flex flex-wrap justify-center gap-3">
          <Link
            href="/overview"
            className="rounded-lg bg-accent px-5 py-2.5 text-sm font-semibold text-background transition-opacity hover:opacity-90"
          >
            View results →
          </Link>
          <Link
            href="/live"
            className="rounded-lg border border-border bg-surface-raised px-5 py-2.5 text-sm font-medium text-foreground transition-colors hover:border-accent/40 hover:bg-accent-dim hover:text-accent"
          >
            Ask a question live
          </Link>
        </div>
      </section>

      {/* ── Problem ───────────────────────────────────────────────────────── */}
      <section>
        <SectionHeading
          label="The problem"
          title="Governance risk hides in the connections"
          subtitle="A single annual report rarely tells the full story. Risk emerges from relationships that span multiple documents, companies and fiscal years — exactly the shape that plain vector search cannot follow."
        />

        <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          <ProblemPoint
            icon="🔗"
            title="Board interlocks"
            body="A director sitting on five boards simultaneously — including one company that later faced a SEBI order — is invisible inside any single filing. You need to traverse the graph."
          />
          <ProblemPoint
            icon="🏦"
            title="Related-party trails"
            body="Material transactions routed through subsidiary chains obscure beneficial ownership. Answering 'who ultimately received the payment' requires multi-hop traversal, not keyword matching."
          />
          <ProblemPoint
            icon="📋"
            title="Auditor independence"
            body="An audit firm auditing the same promoter-group entities for 15 years is a red flag that only appears when you join auditor records across companies and fiscal years."
          />
          <ProblemPoint
            icon="📉"
            title="Promoter pledge cascades"
            body="A promoter pledging shares in one entity to fund acquisition in another creates a risk chain that plain RAG cannot reconstruct — it has no notion of traversal depth."
          />
          <ProblemPoint
            icon="📅"
            title="Temporal changes"
            body="A director who resigned the quarter before a regulatory action is not suspicious in any one document. It becomes significant only when events are joined across time."
          />
          <ProblemPoint
            icon="❌"
            title="Why RAG fails here"
            body="RAG returns the top-K most similar chunks and asks the LLM to reason. It cannot aggregate, cannot join two facts from different PDFs, and cannot follow a chain of relationships."
          />
        </div>
      </section>

      {/* ── Graph visual ──────────────────────────────────────────────────── */}
      <section>
        <SectionHeading
          label="The graph"
          title="One knowledge graph, three retrieval strategies"
          subtitle="Every extracted fact is an edge carrying a verbatim source quote and the PDF page it came from. The same graph powers all three pipelines."
        />

        <div className="mx-auto max-w-3xl rounded-xl border border-border bg-surface-raised p-6">
          <p className="mb-4 text-center text-[10px] font-medium uppercase tracking-widest text-muted">
            InterlockV2 · live TigerGraph graph · 5 companies · FY2021–24
          </p>
          <div className="grid grid-cols-5 gap-2 items-center text-center">
            <GraphNode label="Tata Steel" sub="Company" accent />
            <div className="text-[10px] text-muted-fg">
              <p>DIRECTOR_OF ×28</p>
              <div className="my-1 h-px bg-border" />
              <p>SUBSIDIARY_OF ×1</p>
            </div>
            <GraphNode label="N. Chandrasekaran" sub="Person" />
            <div className="text-[10px] text-muted-fg">
              <p>DIRECTOR_OF ×28</p>
              <div className="my-1 h-px bg-border" />
              <p>AUDITED_BY ×8</p>
            </div>
            <GraphNode label="Tata Motors" sub="Company" accent />
          </div>
          <div className="mt-4 grid grid-cols-3 gap-2">
            <GraphNode label="S R B C & CO LLP" sub="AuditFirm" />
            <GraphNode label="Bajaj Finance" sub="Company" accent />
            <GraphNode label="Bajaj Finserv" sub="Company" accent />
          </div>
          <div className="mt-4 border-t border-border pt-3 grid grid-cols-3 gap-2 text-center">
            <div>
              <p className="text-lg font-semibold text-foreground">18,994</p>
              <p className="text-xs text-muted-fg">Chunks with embeddings</p>
            </div>
            <div>
              <p className="text-lg font-semibold text-foreground">3,240</p>
              <p className="text-xs text-muted-fg">MENTIONS edges</p>
            </div>
            <div>
              <p className="text-lg font-semibold text-foreground">26</p>
              <p className="text-xs text-muted-fg">Source documents</p>
            </div>
          </div>
        </div>
      </section>

      {/* ── Three pipelines ───────────────────────────────────────────────── */}
      <section>
        <SectionHeading
          label="The solution"
          title="Three pipelines, same question, same graph"
          subtitle="All three share the same evidence budget, the same answer prompt and the same verifier. The only difference is how they retrieve evidence."
        />

        <div className="grid gap-4 md:grid-cols-3">
          <PipelineCard
            icon="🔍"
            name="RAG"
            color="#60a5fa"
            how="Embeds the question with all-MiniLM-L6-v2, searches the vector index for the top-40 chunks, fuses with BM25 keyword scores via reciprocal rank fusion, fits a 4,000-token evidence budget, and makes one LLM call."
            best="Single-fact lookups where the answer lives in one passage"
            cost="1 LLM call per question"
          />
          <PipelineCard
            icon="🕸️"
            name="GraphRAG"
            color="#34d399"
            how="A helper LLM call extracts entity mentions and relation types from the question. Those entities are linked to graph nodes, expanded up to 2 hops via an installed GSQL query, and the resulting triples + linked chunks are ranked and passed to the answer call."
            best="1–2 hop structural questions: shared directors, auditor tenure"
            cost="2 LLM calls per question"
          />
          <PipelineCard
            icon="🤖"
            name="Agentic GraphRAG"
            color="#a78bfa"
            how="A tool-calling loop runs under hard step, token and wall-clock budgets. The model picks from search_text, find_entity, neighbors, expand_hop, graph_query and calculate. After the loop, a separate verifier checks each claim against the evidence."
            best="Multi-hop trails, aggregations, temporal cascades, auditor chains"
            cost="3–8 LLM calls per question"
          />
        </div>
      </section>

      {/* ── Numbers ───────────────────────────────────────────────────────── */}
      <section>
        <SectionHeading
          label="By the numbers"
          title="What has been built and measured"
        />

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatBox value="5" label="Companies" sub="TATAMOTORS · TATASTEEL · BAJFINANCE · BAJAJFINSV + 1" />
          <StatBox value="26" label="Annual reports" sub="FY2021-22 through FY2023-24" />
          <StatBox value="18,994" label="Text chunks" sub="Embedded with sentence-transformers" />
          <StatBox value="60%" label="GraphRAG accuracy" sub="dev split · 5 questions · live graph" />
        </div>
        <div className="mt-4 grid gap-4 sm:grid-cols-3">
          <StatBox value="100%" label="RAG accuracy" sub="test split · 12 questions" />
          <StatBox value="40%" label="Agent accuracy" sub="dev split · 5 questions · no-graph baseline" />
          <StatBox value="28" label="Board director edges" sub="DIRECTOR_OF with provenance" />
        </div>
        <p className="mt-4 text-center text-xs text-muted-fg">
          All figures from stored evaluation runs. 17 questions total, 3 of 6 planned categories.
          The 100% RAG interval is degenerate at n=12 — read it as a working baseline, not a guarantee.
        </p>
      </section>

      {/* ── Architecture ──────────────────────────────────────────────────── */}
      <section>
        <SectionHeading
          label="Architecture"
          title="Offline build · Online answer · Honest evaluation"
          subtitle="A modular pipeline that turns public PDFs into a knowledge graph, then measures exactly where each retrieval strategy wins and loses."
        />

        <div className="grid gap-4 md:grid-cols-3">
          {[
            {
              step: "01",
              title: "Offline build",
              color: "#f59e0b",
              items: [
                "Fetch PDFs from NSE/BSE (rate-limited, content-addressed)",
                "PyMuPDF + pdfplumber parse text and tables with page numbers",
                "Section detector locates governance, RPT, auditor, board reports",
                "LLM extracts 6 typed record schemas with verbatim source quotes",
                "Grounding check: every quote verified against its stated page",
                "Union-Find entity resolver links mentions across documents",
                "GSQL loader writes vertices, edges and provenance into TigerGraph",
                "sentence-transformers embeds all chunks into a local vector index",
              ],
            },
            {
              step: "02",
              title: "Online answer",
              color: "#22d3ee",
              items: [
                "FastAPI /compare runs all three pipelines concurrently in threads",
                "Each pipeline returns AnswerResult with citations, evidence and trace",
                "Demo mode serves cached answers instantly — no API key needed",
                "Groq free-tier LLM (200k tokens/day); CPU-only torch for embeddings",
                "Traces capture every LLM turn, tool call, token count and latency",
                "Read cache (TTL) prevents round-trips to remote Turso DB",
                "CORS configured for local dev and Vercel deployment",
              ],
            },
            {
              step: "03",
              title: "Evaluation",
              color: "#a78bfa",
              items: [
                "17 questions across single_fact, unanswerable, numerical categories",
                "Gold answers verified against source PDF pages by a second reader",
                "Exact-match normalisation for company name aliases",
                "Bootstrap 95% confidence intervals with 10,000 resamples",
                "Faithfulness judge (120B model) checks claims against evidence only",
                "Failure taxonomy: retrieval_miss, entity_link_error, hallucination…",
                "Paired-difference test: a lead is clear only when CI excludes zero",
                "Dashboard renders all runs; results traceable to a git commit",
              ],
            },
          ].map((col) => (
            <div key={col.step} className="rounded-xl border border-border bg-surface-raised p-5">
              <div className="mb-4 flex items-center gap-3">
                <span
                  className="flex h-7 w-7 items-center justify-center rounded-md text-xs font-bold"
                  style={{ background: `${col.color}22`, color: col.color }}
                >
                  {col.step}
                </span>
                <h3 className="font-semibold text-foreground">{col.title}</h3>
              </div>
              <ul className="space-y-2">
                {col.items.map((item) => (
                  <li key={item} className="flex gap-2 text-xs leading-relaxed text-muted-fg">
                    <span className="mt-0.5 flex-shrink-0 text-muted">›</span>
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </section>

      {/* ── CTA ───────────────────────────────────────────────────────────── */}
      <section className="rounded-2xl border border-accent/20 bg-accent-glow p-10 text-center">
        <p className="text-xs font-semibold uppercase tracking-widest text-accent mb-3">
          Explore the results
        </p>
        <h2 className="text-2xl font-semibold text-foreground">
          See where the graph makes the difference
        </h2>
        <p className="mx-auto mt-3 max-w-xl text-sm leading-relaxed text-muted-fg">
          The dashboard shows per-category accuracy with bootstrap CIs, cost and latency
          trade-offs, a full failure breakdown, and a side-by-side inspector for every question.
        </p>
        <div className="mt-8 flex flex-wrap justify-center gap-3">
          <Link
            href="/overview"
            className="rounded-lg bg-accent px-6 py-2.5 text-sm font-semibold text-background transition-opacity hover:opacity-90"
          >
            Results overview
          </Link>
          <Link
            href="/inspector"
            className="rounded-lg border border-border bg-surface-raised px-6 py-2.5 text-sm font-medium text-foreground transition-colors hover:border-accent/40 hover:text-accent"
          >
            Question inspector
          </Link>
          <Link
            href="/live"
            className="rounded-lg border border-border bg-surface-raised px-6 py-2.5 text-sm font-medium text-foreground transition-colors hover:border-cyan/40 hover:text-cyan"
          >
            Ask live
          </Link>
        </div>
      </section>

    </div>
  );
}
