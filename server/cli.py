import argparse
import sys
from pathlib import Path

import yaml

from server.ingest.coverage import generate_coverage
from server.ingest.fetcher import PoliteClient, fetch_all
from server.ingest.inbox import ingest_inbox
from server.ingest.models import CompaniesFile
from server.ingest.sources.exchange import ExchangeAdapter
from server.llm.gateway import call_llm
from server.llm.models import LLMMessage, LLMRequest
from server.parse.pdf import parse_all
from server.parse.sections import detect_all_sections
from server.store.db import migrate

COMPANIES_YAML = Path("config/companies.yaml")
FETCH_USER_AGENT = "Interlock-TG research project (contact: prajwalpriyadarshan@gmail.com)"
FETCH_DELAY_SECONDS = 3.0
FETCH_TIMEOUT_SECONDS = 60.0
FETCH_MAX_RETRIES = 3


def main() -> None:
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

    # coverage command
    subparsers.add_parser("coverage", help="Regenerate docs/coverage.md")

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
        client = PoliteClient(
            user_agent=FETCH_USER_AGENT,
            delay=FETCH_DELAY_SECONDS,
            timeout=FETCH_TIMEOUT_SECONDS,
            max_retries=FETCH_MAX_RETRIES,
        )
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

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
