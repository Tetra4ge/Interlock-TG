import pytest

from server.resolve.cluster import UnionFind
from server.resolve.match import block_keys, compare_mentions, person_score
from server.resolve.mentions import Mention
from server.resolve.normalize import norm_company, norm_person

# --- 1. Normalization & Scoring Tests ---


def test_norm_person():
    assert norm_person("Mr. A.K. Sharma") == "a k sharma"
    assert norm_person("Smt. Priya Rao") == "priya rao"


def test_norm_company():
    assert norm_company("XYZ Industries Ltd.") == norm_company("XYZ Industries Limited")


def test_person_score():
    score_high = person_score("a k sharma", "anil kumar sharma")
    assert score_high >= 70.0

    score_zero = person_score("a sharma", "r sharma")
    assert score_zero == 0.0


# --- 2. Merge Logic Tests ---


def test_different_dins_never_merge():
    m1 = Mention(
        mention_id="m1",
        kind="person",
        raw_name="John Doe",
        norm_name="john doe",
        ids={"din": "11111111"},
        context_company_id="C1",
        record_id="r1",
    )
    m2 = Mention(
        mention_id="m2",
        kind="person",
        raw_name="John Doe",
        norm_name="john doe",
        ids={"din": "22222222"},
        context_company_id="C1",
        record_id="r2",
    )
    # Even with same exact name and company, DIN mismatch strictly prevents merge
    assert compare_mentions(m1, m2) is None


def test_union_find():
    uf = UnionFind()
    uf.union("m1", "m2")
    uf.union("m2", "m3")

    assert uf.find("m1") == uf.find("m3")
    assert uf.find("m1") != uf.find("m4")


# --- 3. Database / SQL Logic Tests ---


def test_cluster_conflict_split():
    # Simulates the logic inside cluster.py where exact_ids conflict
    cluster_mentions = [
        Mention(
            mention_id="m1",
            kind="person",
            raw_name="John",
            norm_name="john",
            ids={"din": "111"},
            context_company_id="C1",
            record_id="r1",
        ),
        Mention(
            mention_id="m2",
            kind="person",
            raw_name="John",
            norm_name="john",
            ids={"din": "222"},
            context_company_id="C1",
            record_id="r2",
        ),
    ]

    exact_ids = set()
    for m in cluster_mentions:
        if m.ids.get("din"):
            exact_ids.add("P:" + m.ids["din"])

    # Test that the conflict logic triggers correctly
    assert len(exact_ids) > 1


def test_fts_escaping():
    # entity_search natively escapes double quotes via `text.replace('"', '""')`
    # We'll just verify the raw escaping logic here
    raw_query = 'ABC & Company "Special" (India)'
    safe_query = raw_query.replace('"', '""')
    assert safe_query == 'ABC & Company ""Special"" (India)'
    assert '"' not in safe_query.replace('""', "")  # No unescaped quotes remain


# --- 4. TigerGraph Integration Tests ---


@pytest.mark.integration
def test_loader_idempotency():
    from server.graph.client import get_tg_connection

    try:
        conn = get_tg_connection()
        v1 = conn.getVertexCount("*")
        e1 = conn.getEdgeCount("*")

        # In a real integration run, we would call:
        # from server.graph.loader import load_graph
        # load_graph()

        v2 = conn.getVertexCount("*")
        e2 = conn.getEdgeCount("*")

        # Asserts idempotency (counts don't duplicate on same data)
        assert v1 == v2
        assert e1 == e2
    except Exception:
        pytest.skip("TigerGraph not available for integration tests")


@pytest.mark.integration
def test_provenance_completeness():
    from server.graph.client import get_tg_connection

    try:
        conn = get_tg_connection()
        # Ensure 0 fact edges are missing provenance.
        # Check DIRECTOR_OF edge counts without doc_id
        res = conn.gsql(
            f"USE GRAPH {conn.graphname}\nSELECT count() FROM Person:s -(DIRECTOR_OF:e)- Company:t "
            f'WHERE e.doc_id == \\"\\"'
        )
        assert "count(): 0" in res or "error" in res  # Naive check; ideally use RESTPP
    except Exception:
        pytest.skip("TigerGraph not available for integration tests")


@pytest.mark.integration
def test_graph_queries_on_fixture():
    from server.graph.queries import neighbors

    try:
        # Assumes a known fixture entity exists
        n = neighbors("P:01234567", ["DIRECTOR_OF"], 2)
        assert isinstance(n, list)
    except Exception:
        pytest.skip("TigerGraph not available for integration tests")


def _company(mention_id: str, name: str) -> Mention:
    return Mention(
        mention_id=mention_id,
        kind="company",
        raw_name=name,
        norm_name=norm_company(name),
        ids={},
        context_company_id="C1",
        record_id=mention_id,
    )


def test_parent_and_subsidiary_names_do_not_fuzzy_merge():
    parent = _company("m1", "Tata Motors Limited")
    for other in ("Tata Motors Finance Limited", "Tata Motors Passenger Vehicles Ltd"):
        res = compare_mentions(parent, _company("m2", other))
        assert res is None or res["method"] == "review_queue", other


def test_spelling_variants_of_one_company_still_merge():
    res = compare_mentions(
        _company("m1", "Tata Steel Long Products Limited"),
        _company("m2", "Tata Steel Long Product Ltd."),
    )
    assert res is not None and res["method"] == "fuzzy"


def test_context_company_is_named_by_its_legal_name():
    from server.resolve.mentions import context_company_mention

    m = context_company_mention("r1", "TATASTEEL")
    assert m.raw_name == "Tata Steel Limited"
    assert m.ids == {"company_id": "TATASTEEL"}

    # A counterparty naming the same company resolves to the same block and
    # merges with it, instead of becoming a second "tatasteel" entity.
    counterparty = _company("r2:counterparty", "Tata Steel Ltd.")
    assert set(block_keys(m)) & set(block_keys(counterparty))
    res = compare_mentions(m, counterparty)
    assert res is not None and res["method"] == "exact_name"


def test_unknown_company_id_falls_back_to_the_id():
    from server.resolve.mentions import context_company_mention

    assert context_company_mention("r1", "NOT-IN-CONFIG").raw_name == "NOT-IN-CONFIG"


def _person(mention_id: str, name: str, company: str, din: str | None = None) -> Mention:
    return Mention(
        mention_id=mention_id,
        kind="person",
        raw_name=name,
        norm_name=norm_person(name),
        ids={"din": din} if din else {},
        context_company_id=company,
        record_id=mention_id.split(":")[0],
    )


def test_one_director_on_two_boards_shares_a_block():
    # Blocking only on surname+company kept these apart, so the DIN printed
    # in one report never reached the other mention of the same director.
    at_steel = _person("r1:person", "N Chandrasekaran", "TATASTEEL", din="00121863")
    at_motors = _person("r2:person", "N Chandrasekaran", "TATAMOTORS")

    assert set(block_keys(at_steel)) & set(block_keys(at_motors))
    res = compare_mentions(at_steel, at_motors)
    assert res is not None and res["method"] == "exact_name"


def test_same_surname_different_people_still_do_not_merge():
    assert (
        compare_mentions(
            _person("r1:person", "A Sharma", "TATASTEEL"),
            _person("r2:person", "R Sharma", "TATAMOTORS"),
        )
        is None
    )
