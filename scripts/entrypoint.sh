#!/usr/bin/env bash
# Container entrypoint. `api` (the default) migrates the run store, optionally seeds the
# sample graph, then serves the FastAPI app. Any other argument is run as a command.
set -euo pipefail

case "${1:-api}" in
  api)
    hl db-migrate
    if [ "${SEED_GRAPH:-false}" = "true" ]; then
      python scripts/seed_graph.py
    fi
    exec uvicorn server.api.main:app --host 0.0.0.0 --port 8000
    ;;
  *)
    exec "$@"
    ;;
esac
