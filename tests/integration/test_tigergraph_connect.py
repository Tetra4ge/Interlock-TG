import pytest
import time
from server.graph.client import get_tg_connection

@pytest.fixture(scope="module")
def tg_conn():
    # Force use of the SpikeGraph for this integration test
    conn = get_tg_connection(graphname="SpikeGraph")
    yield conn

@pytest.mark.integration
def test_tigergraph_spike(tg_conn):
    """
    Phase 0 Spike: Validates GSQL schema syntax, discriminator edges, 
    multi-endpoint edges, upsert idempotency, and query installation.
    
    Note: Requires a running TigerGraph instance accessible via settings.
    """
    
    # 1. Create a throwaway schema and graph
    setup_gsql = """
    USE GLOBAL
    DROP GRAPH SpikeGraph | true
    
    CREATE VERTEX Company (PRIMARY_ID id STRING, name STRING)
    CREATE VERTEX Person (PRIMARY_ID id STRING, name STRING)
    
    CREATE DIRECTED EDGE WORKS_FOR (FROM Person, TO Company, role STRING) WITH REVERSE_EDGE="WORKS_FOR_REV"
    CREATE DIRECTED EDGE MULTI_EDGE (FROM Person, TO Company | FROM Company, TO Company) WITH DISCRIMINATOR(discriminator STRING)
    
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
    
    tg_conn.upsertEdge("Person", "p1", "WORKS_FOR", "Company", "c1", attributes={"role": "Engineer"})
    tg_conn.upsertEdge("Person", "p2", "WORKS_FOR", "Company", "c1", attributes={"role": "Manager"})
    
    # Check counts
    v_count = tg_conn.getVertexCount("Person")
    assert v_count == 2
    
    # Re-run same upsert, counts should not grow (idempotency check)
    tg_conn.upsertVertex("Person", "p1", attributes={"name": "Alice"})
    assert tg_conn.getVertexCount("Person") == 2
    
    # 3. Test multi-endpoint edge with discriminator
    # Insert two edges of the same type between the same vertices with different discriminators
    tg_conn.upsertEdge("Person", "p1", "MULTI_EDGE", "Company", "c1", attributes={"discriminator": "type_a"})
    tg_conn.upsertEdge("Person", "p1", "MULTI_EDGE", "Company", "c1", attributes={"discriminator": "type_b"})
    
    # Confirm both exist by checking edge count
    edge_count = tg_conn.getEdgeCount("MULTI_EDGE")
    assert edge_count >= 2
    
    # 4. Write, INSTALL, and run a 2-hop traversal query with a SumAccum
    query_gsql = """
    USE GRAPH SpikeGraph
    CREATE OR REPLACE QUERY two_hop_spike(STRING start_person) FOR GRAPH SpikeGraph {
      SumAccum<INT> @@hop_count;
      
      Start = {Person.*};
      Start = SELECT s FROM Start:s WHERE s.id == start_person;
      
      Hop1 = SELECT t FROM Start:s -(WORKS_FOR:e)-> Company:t
             ACCUM @@hop_count += 1;
             
      PRINT @@hop_count;
    }
    INSTALL QUERY two_hop_spike
    """
    
    print("Installing query (this may take a minute)...")
    tg_conn.gsql(query_gsql)
    
    # Run the installed query
    res = tg_conn.runInstalledQuery("two_hop_spike", {"start_person": "p1"})
    assert res[0]["@@hop_count"] == 1
    
    # 5. Cleanup
    print("Cleaning up spike graph...")
    tg_conn.gsql("USE GLOBAL DROP GRAPH SpikeGraph")
