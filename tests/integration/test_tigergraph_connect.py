import time

import pytest

from server.graph.client import get_tg_connection


@pytest.fixture(scope="module")
def tg_conn():
    # Force use of the SpikeGraph for this integration test
    conn = get_tg_connection(graphname="SpikeGraph")
    yield conn


def _wait_for(fn, expected, timeout_s: float = 15.0, interval_s: float = 1.0):
    """Poll `fn()` until it returns `expected` or `timeout_s` elapses.

    Freshly created graphs on this TigerGraph (Community, Docker) lag: an
    upsert's REST call returns success immediately, but GPE/GSE take a few
    seconds after `CREATE GRAPH` before writes are visible to read queries
    like `getVertexCount`. A fixed `time.sleep(2)` was not reliably long
    enough and made this test flaky; poll instead of guessing a fixed delay.
    """
    deadline = time.monotonic() + timeout_s
    last = None
    while time.monotonic() < deadline:
        last = fn()
        if last == expected:
            return last
        time.sleep(interval_s)
    return last


@pytest.mark.integration
def test_tigergraph_spike(tg_conn):
    """
    Phase 0 Spike: Validates GSQL schema syntax, discriminator edges,
    multi-endpoint edges, upsert idempotency, and query installation.

    Note: Requires a running TigerGraph instance accessible via settings.
    """

    # 1. Create a throwaway schema and graph
    # (`DROP GRAPH`/`DROP VERTEX`/`DROP EDGE` on objects that don't exist yet print
    # an error but are non-fatal in the GSQL shell; the script continues to the next
    # statement either way. `| true` is a bash idiom, not valid GSQL, and previously
    # broke this script outright.
    # Vertex/edge TYPES are global objects independent of the GRAPH that references
    # them, so `DROP GRAPH` alone does not make this script rerunnable -- a prior run
    # leaves Company/Person/WORKS_FOR/MULTI_EDGE behind and the next CREATE VERTEX
    # fails with "already used by another object". Edges must be dropped before the
    # vertex types they reference, or the drop is rejected. `CASCADE` is required
    # because the installed query `two_hop_spike` is a dependent object of the graph;
    # without it, `DROP GRAPH` fails whenever a prior run's own cleanup step also
    # failed to cascade, which then made every drop below fail too.)
    setup_gsql = """
    USE GLOBAL
    DROP GRAPH SpikeGraph CASCADE
    DROP EDGE WORKS_FOR
    DROP EDGE MULTI_EDGE
    DROP VERTEX Company
    DROP VERTEX Person

    CREATE VERTEX Company (PRIMARY_ID id STRING, name STRING)
    CREATE VERTEX Person (PRIMARY_ID id STRING, name STRING)
    
    CREATE DIRECTED EDGE WORKS_FOR (FROM Person, TO Company, role STRING)
        WITH REVERSE_EDGE="WORKS_FOR_REV"
    CREATE DIRECTED EDGE MULTI_EDGE (FROM Person, TO Company | FROM Company, TO Company,
        DISCRIMINATOR(edge_kind STRING))

    CREATE GRAPH SpikeGraph (Company, Person, WORKS_FOR, WORKS_FOR_REV, MULTI_EDGE)
    """

    print("Setting up schema...")
    try:
        res = tg_conn.gsql(setup_gsql)
        print(res)
    except Exception as e:
        pytest.skip(f"Could not connect to TigerGraph or create graph (is it running?): {e}")

    # Give TigerGraph a moment to initialize the graph space
    time.sleep(2)

    # 2. Upsert vertices and edges
    print("Upserting data...")
    tg_conn.upsertVertex("Company", "c1", attributes={"name": "TigerGraph"})
    tg_conn.upsertVertex("Person", "p1", attributes={"name": "Alice"})
    tg_conn.upsertVertex("Person", "p2", attributes={"name": "Bob"})

    tg_conn.upsertEdge(
        "Person", "p1", "WORKS_FOR", "Company", "c1", attributes={"role": "Engineer"}
    )
    tg_conn.upsertEdge("Person", "p2", "WORKS_FOR", "Company", "c1", attributes={"role": "Manager"})

    # Check counts (poll: see _wait_for docstring for why this isn't a flat assert)
    v_count = _wait_for(lambda: tg_conn.getVertexCount("Person"), 2)
    assert v_count == 2

    # Re-run same upsert, counts should not grow (idempotency check)
    tg_conn.upsertVertex("Person", "p1", attributes={"name": "Alice"})
    assert tg_conn.getVertexCount("Person") == 2

    # 3. Test multi-endpoint edge with discriminator
    # Insert two edges of the same type between the same vertices with different discriminators
    tg_conn.upsertEdge(
        "Person", "p1", "MULTI_EDGE", "Company", "c1", attributes={"edge_kind": "type_a"}
    )
    tg_conn.upsertEdge(
        "Person", "p1", "MULTI_EDGE", "Company", "c1", attributes={"edge_kind": "type_b"}
    )

    # Confirm both exist by checking edge count
    edge_count = _wait_for(lambda: tg_conn.getEdgeCount("MULTI_EDGE"), 2)
    assert edge_count >= 2

    # 4. Write, INSTALL, and run a 2-hop traversal query with a SumAccum
    # `id` is the vertex's PRIMARY_ID, not a queryable attribute -- `WHERE s.id ==
    # start_person` fails to type-check ("no valid vertex type"). The correct idiom
    # is a typed VERTEX<Person> parameter, seeded directly as the start set.
    query_gsql = """
    USE GRAPH SpikeGraph
    CREATE OR REPLACE QUERY two_hop_spike(VERTEX<Person> start_person) FOR GRAPH SpikeGraph {
      SumAccum<INT> @@hop_count;

      Start = {start_person};

      Hop1 = SELECT t FROM Start:s -(WORKS_FOR:e)-> Company:t
             ACCUM @@hop_count += 1;

      PRINT @@hop_count;
    }
    INSTALL QUERY two_hop_spike
    """

    print("Installing query (this may take a minute)...")
    install_res = tg_conn.gsql(query_gsql)
    print(install_res)
    assert "Query installation finished" in install_res

    # Run the installed query. VERTEX<T> params take a 1-tuple; a plain value is
    # deprecated (falls back to a slower GET request with a REST-30000 warning).
    res = tg_conn.runInstalledQuery("two_hop_spike", {"start_person": ("p1",)})
    assert res[0]["@@hop_count"] == 1

    # 5. Cleanup (CASCADE: also drops the installed query, see the setup comment above)
    print("Cleaning up spike graph...")
    tg_conn.gsql("USE GLOBAL DROP GRAPH SpikeGraph CASCADE")
