import argparse
import sys

from server.llm.gateway import call_llm
from server.llm.models import LLMMessage, LLMRequest
from server.store.db import migrate


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

    args = parser.parse_args()

    if args.command == "db-migrate":
        print("Running Turso database migrations...")
        migrate()
        print("Done. Migrations applied.")

    elif args.command == "llm-ping":
        print("Sending message to LLM (groq: llama-3.1-8b-instant)...")
        req = LLMRequest(
            provider="groq",
            model="llama-3.1-8b-instant",
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
