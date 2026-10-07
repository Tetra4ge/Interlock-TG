import argparse
import os
import sys
from pathlib import Path

import yaml

from server.common.ids import generate_id
from server.extract.evaluate import evaluate_run
from server.extract.review import review_cli
from server.extract.runner import extract_all
from server.ingest.coverage import generate_coverage
from server.ingest.fetcher import PoliteClient, fetch_all
from server.ingest.inbox import ingest_inbox
from server.ingest.models import CompaniesFile
from server.ingest.sources.exchange import ExchangeAdapter
from server.llm.gateway import call_llm
from server.llm.models import LLMMessage, LLMRequest
from server.parse.chunk import chunk_all
from server.parse.pdf import parse_all
from server.parse.sections import detect_all_sections
from server.settings import ROOT
from server.store.db import migrate

COMPANIES_YAML = Path("config/companies.yaml")
PIPELINE_YAML = Path("config/pipeline.yaml")


def _fetch_config() -> dict:
    data = yaml.safe_load(PIPELINE_YAML.read_text()) if PIPELINE_YAML.exists() else {}
    cfg = (data or {}).get("fetch") or {}
    return {
        "user_agent": cfg.get("user_agent", "Interlock-TG research project"),
        "delay": float(cfg.get("delay_seconds", 3.0)),
        "timeout": float(cfg.get("timeout_seconds", 60.0)),
        "max_retries": int(cfg.get("max_retries", 3)),
    }


def main() -> None:
    # data/, config/ and the GSQL/prompt files are all addressed relative to
    # the repo root, so `hl` must behave the same from any working directory.
    os.chdir(ROOT)

    parser = argparse.ArgumentParser(description="Interlock-TG CLI")
    subparsers = parser.add_subparsers(dest="command")

    # db-migrate command
    subparsers.add_parser("db-migrate", help="Run Turso/libSQL database migrations")

    # llm-ping command
    ping_parser = subparsers.add_parser(
        "llm-ping", help="Ping the LLM Gateway to test config and DB logging"
    )
    ping_parser.add_argument("message", type=str, help="Message to send to the LLM")

    # fetch command
    fetch_parser = subparsers.add_parser(
        "fetch", help="Run source adapters to fetch documents (respects rate limits)"
    )
    fetch_parser.add_argument("--company", type=str, default=None, help="Filter by company_id")

    # ingest-inbox command
    subparsers.add_parser("ingest-inbox", help="Register manually-downloaded files from data/inbox")

    # parse command
    subparsers.add_parser("parse", help="Parse registered PDFs into pages and tables")

    # detect-sections command
    subparsers.add_parser("detect-sections", help="Detect specific sections within parsed PDFs")

    # chunk command
    subparsers.add_parser("chunk", help="Break parsed PDFs into token-limited chunks")

    # extract command
    extract_parser = subparsers.add_parser(
        "extract", help="Extract typed records from documents using LLMs"
    )
    extract_parser.add_argument(
        "--run-id", type=str, default="run-test", help="ID for this extraction run"
    )

    # review command
    subparsers.add_parser("review", help="Interactive CLI to process the manual review queue")

    # evaluate command
    eval_parser = subparsers.add_parser(
        "evaluate", help="Evaluate extraction run quality and costs"
    )
    eval_parser.add_argument(
        "--run-id", type=str, default="run-test", help="ID for the extraction run to evaluate"
    )

    # coverage command
    subparsers.add_parser("coverage", help="Generate the docs/coverage.md report")

    # build-graph command
    bg_parser = subparsers.add_parser(
        "build-graph", help="Run the entire ingestion and graph build pipeline"
    )
    bg_parser.add_argument(
        "--from", dest="start_from", type=str, default="migrate", help="Step to start from"
    )
    bg_parser.add_argument(
        "--reset-graph", action="store_true", help="Clear the TigerGraph store first"
    )
    bg_parser.add_argument("--yes", action="store_true", help="Skip confirmation for --reset-graph")

    # quality command
    subparsers.add_parser("quality", help="Generate the docs/data-quality.md report")

    # sample graph commands
    subparsers.add_parser("export-sample", help="Export a subset of the TigerGraph graph to JSONL")
    subparsers.add_parser(
        "import-sample", help="Import the sample graph JSONL back into TigerGraph"
    )

    # ask command
    ask_parser = subparsers.add_parser("ask", help="Ask a question through an answer pipeline")
    ask_parser.add_argument("question", type=str, help="The question to ask")
    ask_parser.add_argument(
        "--pipeline", type=str, default="rag", help="Pipeline name (default: rag)"
    )

    eval_parser = subparsers.add_parser(
        "eval", help="Run an eval split through a pipeline and score it"
    )
    eval_parser.add_argument("--pipeline", type=str, default="rag")
    eval_parser.add_argument("--split", type=str, default="test", choices=["dev", "test"])
    eval_parser.add_argument("--limit", type=int, default=None)
    eval_parser.add_argument("--run-id", type=str, default=None, help="Reuse an id to resume a run")
    eval_parser.add_argument(
        "--judge", action="store_true", help="Score faithfulness with the LLM judge"
    )

    args = parser.parse_args()

    if args.command == "db-migrate":
        print("Running Turso database migrations...")
        migrate()
        print("Done. Migrations applied.")

    elif args.command == "fetch":
        companies_file = CompaniesFile(**yaml.safe_load(COMPANIES_YAML.read_text()))
        if args.company:
            companies_file.companies = [
                c for c in companies_file.companies if c.company_id == args.company
            ]
        client = PoliteClient(**_fetch_config())
        try:
            fetch_all(companies_file, [ExchangeAdapter()], client)
        finally:
            client.close()
        print("Fetch run complete. See fetch_attempts / `hl coverage` for results.")

    elif args.command == "ingest-inbox":
        report = ingest_inbox()
        print(f"Registered: {report['registered']}, Duplicates: {report['duplicates']}")
        if report["bad_names"]:
            print("Bad names (left in inbox):")
            for name in report["bad_names"]:
                print(f"  - {name}")

    elif args.command == "coverage":
        generate_coverage()
        print("Wrote docs/coverage.md")

    elif args.command == "parse":
        parse_all()
        print("Parsing complete.")

    elif args.command == "detect-sections":
        detect_all_sections()

    elif args.command == "chunk":
        chunk_all()

    elif args.command == "extract":
        extract_all(args.run_id)

    elif args.command == "review":
        review_cli()

    elif args.command == "evaluate":
        evaluate_run(args.run_id)

    elif args.command == "llm-ping":
        print("Sending message to LLM (groq: openai/gpt-oss-20b)...")
        req = LLMRequest(
            provider="groq",
            model="openai/gpt-oss-20b",
            messages=[LLMMessage(role="user", content=args.message)],
            max_tokens=100,
        )
        res = call_llm(req)

        if res.error:
            print(f"\n❌ Error: {res.error}", file=sys.stderr)
        else:
            print(f"\n✅ Response: {res.content}")

        print("\nStats:")
        print(f"  Cache Hit: {res.cache_hit}")
        print(f"  Tokens   : {res.tokens_in} in / {res.tokens_out} out")
        print(f"  Latency  : {res.latency_ms} ms")
        print(f"  Cost     : ${res.cost_usd:.6f}")

    elif args.command == "build-graph":
        if args.reset_graph:
            if not args.yes:
                print("WARNING: --reset-graph will CLEAR all vertices and edges from TigerGraph.")
                ans = input("Type 'yes' to continue: ")
                if ans.lower() != "yes":
                    print("Aborting.")
                    sys.exit(1)
            from server.graph.client import get_tg_connection

            print("Clearing graph store...")
            conn = get_tg_connection()
            # In TigerGraph v3/v4 CLEAR GRAPH STORE -HARD wipes data.
            conn.gsql(f"USE GRAPH {conn.graphname}\nCLEAR GRAPH STORE -HARD")
            print("Graph store cleared.")

        def build_entity_index() -> None:
            from server.store.db import connect

            db = connect()
            print("Rebuilding FTS5 entities index...")
            db.execute("DROP TABLE IF EXISTS entities_fts")
            db.execute("""
                CREATE VIRTUAL TABLE entities_fts USING fts5(
                    entity_id UNINDEXED,
                    canonical_name,
                    aliases_text,
                    kind UNINDEXED
                )
            """)
            db.execute("""
                INSERT INTO entities_fts (entity_id, canonical_name, aliases_text, kind)
                SELECT entity_id, canonical_name, aliases_text, kind FROM entities
            """)
            db.commit()
            db.close()

        from server.embed.index import build_vector_index
        from server.graph.loader import load_graph
        from server.graph.mentions_link import run_mentions_link
        from server.graph.schema import apply_schema, install_queries
        from server.resolve.cluster import run_clustering

        def schema_step() -> None:
            apply_schema()
            install_queries()

        steps = [
            ("migrate", lambda: migrate()),
            ("schema", schema_step),
            ("parse", lambda: parse_all()),
            ("sections", lambda: detect_all_sections()),
            ("chunk", lambda: chunk_all()),
            ("extract", lambda: extract_all("default-run")),
            ("resolve", lambda: run_clustering()),
            ("load", lambda: load_graph("default-run")),
            ("mentions", lambda: run_mentions_link()),
            ("embed", lambda: build_vector_index()),
            ("entity-index", lambda: build_entity_index()),
        ]

        start_idx = 0
        for i, (name, _) in enumerate(steps):
            if name == args.start_from:
                start_idx = i
                break

        for i in range(start_idx, len(steps)):
            name, func = steps[i]
            print(f"\n--- Running Step: {name} ---")
            func()

        print("\n✅ build-graph pipeline completed successfully!")

    elif args.command == "quality":
        from server.reporting.quality import generate_quality_report

        generate_quality_report()
        print("Data quality report generated at docs/data-quality.md")

    elif args.command == "export-sample":
        from server.graph.export import export_sample

        export_sample()

    elif args.command == "import-sample":
        from server.graph.export import import_sample

        import_sample()

    elif args.command == "ask":
        from server.pipelines.base import REGISTRY, load_all

        load_all()
        pipeline = REGISTRY.get(args.pipeline)
        if pipeline is None:
            print(
                f"Unknown pipeline: {args.pipeline!r}. Available: {sorted(REGISTRY)}",
                file=sys.stderr,
            )
            sys.exit(1)

        request_id = generate_id()
        result = pipeline.answer(args.question, request_id)

        print(
            f"[{result.pipeline}] status={result.status.value}  type={result.answer_type.value}  "
            f"cost=${result.usage.cost_usd:.4f}  latency={result.usage.latency_ms / 1000:.1f}s  "
            f"llm_calls={result.usage.llm_calls}"
        )
        print(f"Answer: {result.answer_short}")
        if result.answer_long:
            print(result.answer_long)
        if result.citations:
            print("Citations:")
            for c in result.citations:
                print(f'  - doc {c.doc_id}, p.{c.page}: "{c.quote}"')
        print("Trace:")
        for s in result.trace:
            print(f"  {s.step} {s.kind:<8} {s.name:<20} {s.latency_ms:>6} ms", end="")
            if s.tokens_in or s.tokens_out:
                print(f"  {s.tokens_in}→{s.tokens_out} tokens", end="")
            if s.error:
                print(f"  ERROR: {s.error}", end="")
            print()

    elif args.command == "eval":
        from server.eval.judge import judge_faithfulness
        from server.eval.models import Question
        from server.eval.persist import persist_run
        from server.eval.runner import QUESTIONS_PATH, RUNS_DIR, load_questions, run_eval
        from server.store.db import connect

        judge = judge_faithfulness if args.judge else None
        summary = run_eval(
            args.pipeline, args.split, run_id=args.run_id, limit=args.limit, judge=judge
        )
        run_dir = RUNS_DIR / summary["run_id"]
        questions: list[Question] = load_questions(QUESTIONS_PATH)
        conn = connect()
        try:
            persist_run(conn, run_dir, questions)
        finally:
            conn.close()

        def _fmt(v: float | None) -> str:
            return "-" if v is None else f"{v:.2f}"

        print(
            f"{'category':<14}{'n':>4}  {'correct':>8}  {'95% CI':>17}  "
            f"{'faith':>6}  {'cite':>6}  {'recall':>6}  {'abstain':>8}"
        )
        for cat, agg in [*summary["by_category"].items(), ("OVERALL", summary["overall"])]:
            lo, hi = agg["correct_ci95"]
            print(
                f"{cat:<14}{agg['n']:>4}  {agg['correct_mean']:>8.2f}  "
                f"[{lo:.2f}, {hi:.2f}]  {_fmt(agg['faithfulness_mean']):>6}  "
                f"{_fmt(agg['citation_accuracy_mean']):>6}  "
                f"{_fmt(agg['evidence_recall_mean']):>6}  {_fmt(agg['abstention_rate']):>8}"
            )
        if summary["overall"]["failures"]:
            print("failures:", summary["overall"]["failures"])
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
