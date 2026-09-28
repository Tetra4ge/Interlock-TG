# ADR 0011: TigerGraph Setup & Spike Validation

## Context
We needed to validate our assumptions about TigerGraph's GSQL syntax, edge discriminators,
and our ability to authenticate and run installed queries using `pyTigerGraph`, against a
real running instance rather than assumption.

## Decision
Deployment: **Docker Compose, local** (`docker-compose.yml`, image `tigergraph/community:latest`,
resolved to **TigerGraph 4.2.5 Community Edition**). The spike ran for real against this
container via `tests/integration/test_tigergraph_connect.py` (`pytest -m integration`),
which passed in 69s end-to-end.

### Key findings, each actually exercised by the spike:
1. **Authentication.** `server/graph/client.py` creates a secret + token dynamically for
   local Docker (no `TG_SECRET` set) and falls back to a provided secret for cloud/Savanna.
   Initially failed with 404s on all GSQL calls — root cause was `TG_HOST` having the
   REST++ port (`:9000`) baked into it, which made `pyTigerGraph` default `gsPort` to 9000
   instead of 14240 (the GraphStudio/GSQL nginx port). Fixed by adding explicit
   `TG_RESTPP_PORT`/`TG_GS_PORT` settings fields and passing both to
   `TigerGraphConnection(...)` rather than relying on inference from `TG_HOST`.
2. **Schema & discriminators.** Multi-endpoint edges
   (`FROM Person, TO Company | FROM Company, TO Company`) and
   `WITH DISCRIMINATOR(discriminator STRING)` both created and accepted upserts without
   error; two `MULTI_EDGE` edges between the same vertex pair with different discriminator
   values both persisted (confirmed via `getEdgeCount`).
3. **Idempotency.** Re-running `upsertVertex` with the same primary ID left `getVertexCount`
   unchanged (2 before and after the repeat upsert).
4. **Installed queries.** A `SumAccum`-based 2-hop traversal query installed
   (~30s compile time on this container) and `runInstalledQuery` returned the expected
   count.
5. **First-boot timing (worth planning around).** After `docker compose up`, the REST++
   healthcheck (`/echo`) went healthy almost immediately, but `GPE` and `GSE` (the storage
   and processing engines) sat in `Warmup` for **~20 minutes** on this machine (Docker
   Desktop: 7.75GB allocated, 10 CPUs) before flipping to `Online`; GSQL itself came online
   faster. GSQL calls 404 and REST++ calls fail with "graph schema not found" during that
   window even though the container reports "healthy." **Do not treat container-healthy as
   TigerGraph-ready** — poll `gadmin status` (via `docker exec`) for GPE/GSE, not just the
   REST++ echo endpoint, before running anything against it. If this recurs consistently,
   raising Docker Desktop's memory allocation is the first thing to try.
6. **Vectors — not verified in this spike.** TigerGraph's own docs claim native vector
   attribute/search support from 4.1 onward, which would cover 4.2.5, but the spike test
   does not create a vector attribute, upsert vectors, or run a top-k search. Treat vector
   support as **unconfirmed** until Phase 3/6 actually exercises it; don't build on the
   assumption it works until then.

## Consequences
- Proceed with the current `TigerGraphConnection` wrapper in `server/graph/client.py`,
  now with explicit `tg_restpp_port`/`tg_gs_port` settings, as the foundation for the rest
  of the hackathon.
- Add a real vector-attribute spike before Phase 3/6 depends on vector search, rather than
  assuming it from the version number alone.
- When bringing TigerGraph up for a demo or a fresh environment, budget for a "healthy but
  not actually ready" window and check `gadmin status`, not just the container healthcheck.
