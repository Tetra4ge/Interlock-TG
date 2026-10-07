import pytest

from server.pipelines.agent.guardrails import (
    QUERY_REGISTRY,
    check_graph_call,
    to_gsql_params,
)

OK_SHARED = {"company_ids": ["C:TATASTEEL", "C:TATAMOTORS"], "fiscal_year": "FY2023-24"}


def _blocked(name: object, params: object) -> str:
    ok, reason, validated = check_graph_call(name, params)
    assert ok is False and validated == {}
    return reason


# --- must block -----------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["drop_graph", "run_gsql", "", "SHARED_DIRECTORS", "shared_directors; DROP ALL",
     "shared_directors ", "shared_directors\n", "chunks_for_entities", None, 5,
     ["shared_directors"]],
)  # fmt: skip
def test_unknown_or_malformed_query_names_are_blocked(name: object) -> None:
    assert "unknown query" in _blocked(name, OK_SHARED)


@pytest.mark.parametrize("params", [None, [], "x", 5])
def test_non_object_params_are_blocked(params: object) -> None:
    assert "params must be an object" in _blocked("shared_directors", params)


@pytest.mark.parametrize(
    ("name", "params"),
    [
        ("shared_directors", {}),
        ("shared_directors", {"fiscal_year": "FY2023-24"}),
        ("path_between", {"source_id": "C:1"}),
        ("path_between", {"source_id": "C:1", "target_id": "C:2", "max_hops": "two"}),
        ("path_between", {"source_id": "C:1", "target_id": "C:2", "max_hops": 50}),
        ("path_between", {"source_id": "C:1", "target_id": "C:2", "max_hops": 0}),
        ("shared_directors", {"company_ids": []}),
        ("shared_directors", {"company_ids": [f"C:{i}" for i in range(11)]}),
        ("shared_directors", {"company_ids": "C:1"}),
        ("shared_directors", {"company_ids": ["C:1"], "fiscal_year": "2023"}),
        ("stake_aggregate", {"company_id": "C:1", "extra": "field"}),
        ("entity_neighbors", {"entity_ids": ["C:1"], "hops": 3}),
    ],
)
def test_missing_wrong_type_or_out_of_range_parameters_are_blocked(name: str, params: dict) -> None:
    assert "invalid parameters" in _blocked(name, params)


@pytest.mark.parametrize(
    "value",
    ['X" ; DELETE', "C:1; DROP", "C:1 OR 1=1", "C:1'", "C:1\n", "C:1\x00", "../../etc", "{x}",
     "C:1)", "a" * 65, "", " ", "C:1 C:2", "SELECT * FROM x", "C:1`"],
)  # fmt: skip
def test_string_parameters_with_quotes_semicolons_or_excess_length_are_blocked(value: str) -> None:
    assert "unexpected characters" in _blocked("stake_aggregate", {"company_id": value})
    assert "unexpected characters" in _blocked("shared_directors", {"company_ids": ["C:1", value]})


@pytest.mark.parametrize(
    "year", ["FY2023-24\n", "fy2023-24", "FY2023-2024", "FY23-24", " FY2023-24"]
)
def test_fiscal_year_must_match_the_format_exactly(year: str) -> None:
    assert "invalid parameters" in _blocked(
        "shared_directors", {"company_ids": ["C:1"], "fiscal_year": year}
    )


def test_injection_in_a_nested_value_is_found() -> None:
    assert "unexpected characters" in _blocked(
        "path_between", {"source_id": "C:1", "target_id": 'C:2" ; DELETE', "max_hops": 2}
    )


# --- must allow -----------------------------------------------------------


def test_valid_call_with_colons_and_hyphens_is_allowed() -> None:
    ok, reason, args = check_graph_call(
        "shared_directors",
        {"company_ids": ["C:BAJAJ-AUTO", "C:TATA_STEEL"], "fiscal_year": "FY2022-23"},
    )
    assert ok and reason == "ok"
    assert args["company_ids"] == ["C:BAJAJ-AUTO", "C:TATA_STEEL"]


def test_optional_parameters_get_their_defaults() -> None:
    ok, _, args = check_graph_call("path_between", {"source_id": "C:1", "target_id": "P:x2"})
    assert ok and args["max_hops"] == 3
    ok, _, args = check_graph_call("shared_directors", {"company_ids": ["C:1"]})
    assert ok and args["fiscal_year"] is None
    ok, _, args = check_graph_call("entity_neighbors", {"entity_ids": ["C:1"]})
    assert ok and args["hops"] == 1


def test_a_64_character_value_is_allowed() -> None:
    ok, _, _ = check_graph_call("stake_aggregate", {"company_id": "C:" + "a" * 62})
    assert ok


# --- parameter mapping ----------------------------------------------------


def test_untyped_vertex_parameters_get_their_type() -> None:
    params = to_gsql_params(
        "path_between", {"source_id": "C:1", "target_id": "P:x2", "max_hops": 2}
    )
    assert params == {"source": ("C:1", "Company"), "target": ("P:x2", "Person"), "max_hops": 2}
    seeds = to_gsql_params(
        "entity_neighbors", {"entity_ids": ["C:1", "A:x9"], "hops": 2, "fiscal_year": None}
    )
    assert seeds["seeds"] == [("C:1", "Company"), ("A:x9", "AuditFirm")]
    assert seeds["fiscal_year"] == ""


def test_typed_parameters_stay_plain() -> None:
    assert to_gsql_params("stake_aggregate", {"company_id": "C:1"}) == {"company": "C:1"}
    assert to_gsql_params("shared_directors", {"company_ids": ["C:1"], "fiscal_year": None}) == {
        "companies": ["C:1"],
        "fiscal_year": "",
    }


def test_an_id_with_no_known_type_prefix_cannot_be_mapped() -> None:
    with pytest.raises(ValueError, match="vertex type"):
        to_gsql_params(
            "path_between", {"source_id": "Automobiles", "target_id": "C:1", "max_hops": 2}
        )


def test_every_registered_query_has_a_parameter_mapping() -> None:
    sample = {
        "shared_directors": {"company_ids": ["C:1"], "fiscal_year": None},
        "path_between": {"source_id": "C:1", "target_id": "C:2", "max_hops": 2},
        "stake_aggregate": {"company_id": "C:1"},
        "entity_neighbors": {"entity_ids": ["C:1"], "hops": 1, "fiscal_year": None},
    }
    assert set(sample) == set(QUERY_REGISTRY)
    for name, args in sample.items():
        assert to_gsql_params(name, args)
