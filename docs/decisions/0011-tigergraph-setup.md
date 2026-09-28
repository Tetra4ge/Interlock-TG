# ADR 0011: TigerGraph Setup & Spike Validation

## Context
We needed to validate our assumptions about TigerGraph's GSQL syntax, edge discriminators, and our ability to securely authenticate and run installed queries using `pyTigerGraph`.

## Decision
We successfully completed the spike in `tests/integration/test_tigergraph_connect.py`. 

### Key Findings:
1. **Authentication:** The `server/graph/client.py` wrapper successfully handles both REST++ token auth (for cloud/Savanna) and basic auth + dynamic secret generation (for local Docker).
2. **Schema & Discriminators:** We validated that multi-endpoint edges (`FROM Person, TO Company | FROM Company, TO Company`) and `WITH DISCRIMINATOR(discriminator STRING)` work as expected for duplicate edge types.
3. **Idempotency:** Re-upserting the exact same vertices (`upsertVertex`) successfully overwrites without duplicating nodes.
4. **Queries:** `runInstalledQuery` successfully executes our `SumAccum` test query.
5. **Vectors:** Vector indexing is supported in the tested TigerGraph version and will be utilized during the Retrieval phase.

## Consequences
- We will proceed with the current `TigerGraphConnection` wrapper in `server/graph/client.py` as the official foundation for the rest of the hackathon.
