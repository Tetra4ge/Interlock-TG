from server.graph.names import map_back, map_forward, reverse_to_forward, to_logical, to_tg


def test_to_tg_prefixes_known_types_only():
    assert to_tg("Company") == "IL_Company"
    assert to_tg("DIRECTOR_OF") == "IL_DIRECTOR_OF"
    # Not one of our schema's names: left alone (e.g. an entity id, not a type name).
    assert to_tg("C:TATAMOTORS") == "C:TATAMOTORS"


def test_to_logical_strips_prefix_and_maps_reverse_edges():
    assert to_logical("IL_Company") == "Company"
    assert to_logical("IL_DIRECTOR_OF") == "DIRECTOR_OF"
    # A reverse-traversed edge comes back under its reverse name; logical code should only
    # ever see the forward (declared) name.
    assert to_logical("IL_HAS_DIRECTOR") == "DIRECTOR_OF"
    assert to_logical("IL_AUDITS") == "AUDITED_BY"
    assert to_logical("not-one-of-ours") == "not-one-of-ours"


def test_reverse_to_forward_covers_every_schema_reverse_edge():
    mapping = reverse_to_forward()
    assert mapping["HAS_DIRECTOR"] == "DIRECTOR_OF"
    assert mapping["AUDITS"] == "AUDITED_BY"
    assert mapping["HAS_PARTY"] == "PARTY_TO"


def test_map_back_recurses_through_nested_query_results():
    raw = [{"edges": [{"e_type": "IL_HAS_DIRECTOR", "v_type": "IL_Company"}]}]
    assert map_back(raw) == [{"edges": [{"e_type": "DIRECTOR_OF", "v_type": "Company"}]}]


def test_map_forward_recurses_into_dict_values():
    """Regression: runInstalledQuery is called with a params dict whose VALUES (not just a
    top-level list) carry type-name strings, e.g. {"edge_types": ["DIRECTOR_OF", ...]}. A
    map_forward that only handled str/list silently left those unmapped, so a query compiled
    with the prefixed literal baked in (from rewrite_gsql at install time) could never match
    the caller's unprefixed parameter -- every result came back empty, with no error."""
    params = {
        "seed_ids": ["C:TATAMOTORS"],
        "edge_types": ["DIRECTOR_OF", "AUDITED_BY"],
        "excluded": ["-"],
        "max_rows": 50,
    }
    mapped = map_forward(params)
    assert mapped == {
        "seed_ids": ["C:TATAMOTORS"],
        "edge_types": ["IL_DIRECTOR_OF", "IL_AUDITED_BY"],
        "excluded": ["-"],
        "max_rows": 50,
    }
