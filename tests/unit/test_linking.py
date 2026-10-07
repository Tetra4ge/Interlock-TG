import json

import pytest

from server.graph import queries
from server.llm.gateway import SpendCapExceeded
from server.llm.models import LLMResponse
from server.pipelines.config import GraphRAGConfig
from server.pipelines.graphrag import linking
from server.pipelines.graphrag.linking import (
    LinkPlan,
    Mention,
    capitalized_phrases,
    fallback_plan,
    link_entities,
    link_mention,
    parse_plan,
    plan_question,
)
from tests.conftest import seed_entities

CFG = GraphRAGConfig()


def _cand(eid: str, name: str, kind: str, score: float, aliases: list[str] | None = None) -> dict:
    return {
        "entity_id": eid,
        "canonical_name": name,
        "kind": kind,
        "score": score,
        "names": [name, *(aliases or [])],
    }


def _stub_search(monkeypatch: pytest.MonkeyPatch, cands: list[dict]) -> list[tuple]:
    calls: list[tuple] = []

    def fake(text: str, kind: str | None = None, limit: int = 5) -> list[dict]:
        calls.append((text, kind))
        return [c for c in cands if kind is None or c["kind"] == kind]

    monkeypatch.setattr(linking, "entity_search", fake)
    return calls


# --- FTS escaping --------------------------------------------------------

HOSTILE = [
    'O"Brien & Sons',
    "Tata (Steel)",
    'x" OR NEAR(',
    "a*b",
    "NOT",
    "AND OR",
    "'; DROP TABLE x;--",
]


@pytest.mark.parametrize("name", HOSTILE)
def test_fts_query_never_breaks_fts5(memdb, name: str) -> None:  # type: ignore[no-untyped-def]
    seed_entities(memdb, [("C:1", "company", "Tata Steel Limited", "")])
    memdb.execute(
        "SELECT entity_id FROM entities_fts WHERE entities_fts MATCH ?", [queries._fts_query(name)]
    ).fetchall()


def test_entity_search_matches_names_with_special_characters(memdb, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    seed_entities(
        memdb,
        [
            ("C:1", "company", 'O"Brien & Sons Limited', ""),
            ("P:1", "person", "Anil Kumar Sharma", "A K Sharma|Anil Sharma"),
        ],
    )
    monkeypatch.setattr(queries, "connect", lambda: memdb)
    assert queries.entity_search('O"Brien & Sons', "company")[0]["entity_id"] == "C:1"
    hit = queries.entity_search("Anil Sharma", "person")[0]
    assert hit["entity_id"] == "P:1"
    assert "A K Sharma" in hit["names"]
    assert queries.entity_search('x" OR NEAR(') == []


def test_multi_token_name_matches_when_tokens_are_not_adjacent(memdb, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    seed_entities(memdb, [("P:1", "person", "Anil Kumar Sharma", "")])
    monkeypatch.setattr(queries, "connect", lambda: memdb)
    assert queries.entity_search("Anil Sharma", "person")[0]["entity_id"] == "P:1"


# --- linking decision ----------------------------------------------------


def test_clear_winner_is_linked(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_search(
        monkeypatch,
        [
            _cand("C:BAJFINANCE", "Bajaj Finance Limited", "company", 76),
            _cand("C:BAJAJFINSV", "Bajaj Finserv Limited", "company", 60),
        ],
    )
    out = link_mention(Mention(text="Bajaj Finance", kind="company"), CFG)
    assert [(e.entity_id, e.status) for e in out] == [("C:BAJFINANCE", "linked")]


def test_close_scores_keep_two_and_mark_ambiguous(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_search(
        monkeypatch,
        [
            _cand("P:1", "Anil Kumar Sharma", "person", 60),
            _cand("P:2", "Rajesh Sharma", "person", 58),
            _cand("P:3", "Meera Sharma", "person", 55),
        ],
    )
    out = link_mention(Mention(text="Sharma", kind="person"), CFG)
    assert len(out) == 2
    assert {e.status for e in out} == {"ambiguous"}


def test_low_scores_are_unlinked(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_search(monkeypatch, [_cand("C:1", "Reliance Industries Limited", "company", 30)])
    out = link_mention(Mention(text="Example Industries", kind="company"), CFG)
    assert len(out) == 1
    assert out[0].status == "unlinked"
    assert out[0].entity_id == ""


def test_mislabelled_kind_retries_without_kind(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _stub_search(
        monkeypatch, [_cand("A:1", "Deloitte Haskins & Sells LLP", "audit_firm", 70)]
    )
    out = link_mention(Mention(text="Deloitte Haskins & Sells", kind="person"), CFG)
    assert out[0].entity_id == "A:1"
    assert [k for _, k in calls] == ["person", None]


def test_alias_can_carry_the_match(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_search(
        monkeypatch,
        [_cand("C:1", "Tata Motors Passenger Vehicles Limited", "company", 40, ["Tata Motors"])],
    )
    out = link_mention(Mention(text="Tata Motors", kind="company"), CFG)
    assert out[0].status == "linked"


def test_sector_mentions_link_to_sector_names_without_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _stub_search(monkeypatch, [])
    out = link_mention(Mention(text="automobiles", kind="sector"), CFG)
    assert out[0].kind == "sector"
    assert out[0].entity_id == "Automobiles"
    assert calls == []
    assert "C:TATAMOTORS" in linking.companies_in_sector("Automobiles")


def test_link_entities_dedupes_and_traces(monkeypatch: pytest.MonkeyPatch, tracer) -> None:  # type: ignore[no-untyped-def]
    _stub_search(monkeypatch, [_cand("C:1", "Tata Steel Limited", "company", 90)])
    out = link_entities(
        [Mention(text="Tata Steel", kind="company"), Mention(text="Tata Steel Ltd")], tracer, CFG
    )
    assert [e.entity_id for e in out] == ["C:1"]
    assert tracer.steps[-1].name == "link_entities"
    assert "C:1" in tracer.steps[-1].output_summary


# --- plan parsing and fallback ------------------------------------------


def test_parse_plan_drops_unknown_relations_and_normalises_years() -> None:
    raw = json.dumps(
        {
            "mentions": [{"text": "Tata Steel", "kind": "weird"}, {"text": " "}, "junk"],
            "relation_types": ["director_of", "NOT_A_REL", "AUDITED_BY", "DIRECTOR_OF"],
            "fiscal_years": ["FY2023-24", "2022-23", "FY 2021 - 22"],
            "is_global": True,
        }
    )
    plan = parse_plan(raw, "Who audited Tata Steel?")
    assert plan.mentions == [Mention(text="Tata Steel", kind="unknown")]
    assert plan.relation_types == ["DIRECTOR_OF", "AUDITED_BY"]
    assert plan.fiscal_years == ["FY2023-24", "FY2021-22"]
    assert plan.is_global is True


def test_parse_plan_adds_a_year_written_in_the_question() -> None:
    plan = parse_plan('{"mentions": []}', "Who audited Tata Steel in FY2023-24?")
    assert plan.fiscal_years == ["FY2023-24"]


@pytest.mark.parametrize("raw", ["not json", "[1, 2]", ""])
def test_parse_plan_rejects_non_objects(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_plan(raw, "q")


def test_capitalized_phrase_fallback() -> None:
    assert capitalized_phrases(
        "Which independent directors of Tata Steel also sit on Tata Motors?"
    ) == [
        "Tata Steel",
        "Tata Motors",
    ]
    assert capitalized_phrases("Did Mr. Sharma serve on Example Industries Ltd?") == [
        "Sharma",
        "Example Industries Ltd",
    ]
    assert capitalized_phrases("who audited the company in FY2023-24?") == []


def test_fallback_plan_has_no_relations_and_only_a_stated_year() -> None:
    plan = fallback_plan("Who audited Tata Steel in FY2023-24?")
    assert plan.source == "fallback"
    assert plan.relation_types == []
    assert plan.fiscal_years == ["FY2023-24"]
    assert [m.text for m in plan.mentions] == ["Tata Steel"]


def _llm(content: str = "", error: str | None = None):  # type: ignore[no-untyped-def]
    return lambda _req: LLMResponse(
        content=content, tokens_in=50, tokens_out=20, cost_usd=0.0, error=error
    )


def test_plan_question_uses_the_model_output(monkeypatch: pytest.MonkeyPatch, tracer) -> None:  # type: ignore[no-untyped-def]
    payload = json.dumps(
        {"mentions": [{"text": "Tata Steel", "kind": "company"}], "relation_types": ["AUDITED_BY"]}
    )
    monkeypatch.setattr(linking, "call_llm", _llm(payload))
    plan = plan_question("Who audited Tata Steel?", tracer)
    assert plan.source == "llm"
    assert plan.relation_types == ["AUDITED_BY"]
    assert tracer.steps[-1].kind == "llm"
    assert tracer.steps[-1].error is None


@pytest.mark.parametrize(
    "resp", [_llm("garbage"), _llm("", error="rate_limited"), _llm('{"mentions": 5}')]
)
def test_plan_question_falls_back_on_bad_output(monkeypatch, tracer, resp) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(linking, "call_llm", resp)
    plan = plan_question("Who audited Tata Steel?", tracer)
    assert plan.source == "fallback"
    assert [m.text for m in plan.mentions] == ["Tata Steel"]
    assert tracer.steps[-1].error.startswith("fallback")


def test_plan_question_falls_back_when_the_call_raises(monkeypatch, tracer) -> None:  # type: ignore[no-untyped-def]
    def boom(_req):  # type: ignore[no-untyped-def]
        raise ConnectionError("network down")

    monkeypatch.setattr(linking, "call_llm", boom)
    assert plan_question("Who audited Tata Steel?", tracer).source == "fallback"


def test_plan_question_lets_the_spend_cap_propagate(monkeypatch, tracer) -> None:  # type: ignore[no-untyped-def]
    def capped(_req):  # type: ignore[no-untyped-def]
        raise SpendCapExceeded("cap")

    monkeypatch.setattr(linking, "call_llm", capped)
    with pytest.raises(SpendCapExceeded):
        plan_question("Who audited Tata Steel?", tracer)


def test_linkplan_defaults_are_empty() -> None:
    assert LinkPlan().mentions == []
