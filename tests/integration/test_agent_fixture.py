from server.llm.gateway import SpendCapExceeded
from server.llm.models import LLMResponse
from server.pipelines.agent.pipeline import AgentPipeline
from server.pipelines.config import AgentConfig
from server.pipelines.models import Status
from tests.integration.agent_harness import (
    STEEL_DOC,
    STEEL_FY23,
    STEEL_FY24,
    TXN,
    answer_json,
    stop_turn,
    tool_turn,
    verdict_json,
)
from tests.unit.graphrag_fixtures import raw_result

SHARMA = "Anil Kumar Sharma | Independent Director"
VERMA = "Rajesh Verma | Independent Director"
OUTAGE_CHUNK = {
    "chunk_id": "abc123abc123-1",
    "doc_id": STEEL_DOC,
    "text": "Anil Kumar Sharma is an independent director.",
    "page_start": 12,
    "page_end": 12,
    "section": "governance",
    "fiscal_year": "FY2023-24",
}
TEMPORAL_Q = "Who was an independent director of Tata Steel in FY2023-24, and who in FY2022-23?"


def board_call(fiscal_year: str | None = None):  # type: ignore[no-untyped-def]
    args = {"entity_id": "C:TATASTEEL", "rel_types": ["DIRECTOR_OF"]}
    if fiscal_year:
        args["fiscal_year"] = fiscal_year
    return tool_turn(("neighbors", args))


def sharma(long: str) -> str:
    return answer_json("Anil Kumar Sharma", long, [("E1", SHARMA)])


def _tools(result) -> list[str]:  # type: ignore[no-untyped-def]
    return [s.name for s in result.trace if s.kind == "tool"]


def test_temporal_question_find_neighbors_neighbors_final(llm, make_graph) -> None:  # type: ignore[no-untyped-def]
    graph = make_graph(STEEL_FY24, STEEL_FY23)  # hops=1: one graph call per neighbors
    llm.agent = [
        tool_turn(("find_entity", {"name": "Tata Steel", "kind": "company"})),
        board_call("FY2023-24"),
        board_call("FY2022-23"),
        stop_turn("Ready: E1, E2"),
    ]  # fmt: skip
    llm.final = [
        answer_json(
            "FY2023-24: Anil Kumar Sharma; FY2022-23: Rajesh Verma",
            "Anil Kumar Sharma served in FY2023-24 [E1] and Rajesh Verma in FY2022-23 [E2].",
            [("E1", SHARMA), ("E2", VERMA)],
            "list",
        )
    ]  # fmt: skip
    llm.verifier = [
        verdict_json(
            ("Anil Kumar Sharma was an independent director in FY2023-24", "SUPPORTED", ["E1"]),
            ("Rajesh Verma was an independent director in FY2022-23", "SUPPORTED", ["E2"]),
        )
    ]

    result = AgentPipeline().answer(TEMPORAL_Q, "req-temporal")

    assert result.pipeline == "agent" and result.status == Status.OK
    assert _tools(result) == ["find_entity", "neighbors", "neighbors"]
    assert result.usage.tool_calls == 3
    # 4 agent turns + the shared final answer + the verifier
    assert result.usage.llm_calls == 6
    # citations resolve through the same labels as RAG/GraphRAG, to real doc and page
    assert {(c.doc_id, c.page) for c in result.citations} == {(STEEL_DOC, 46), (STEEL_DOC, 41)}
    # fiscal years reached the graph calls
    assert graph.expand_calls[0]["edge_types"] == ["DIRECTOR_OF"]
    # both years' facts are in the evidence the answer saw
    texts = " ".join(e.text for e in result.evidence)
    assert "FY2023-24" in texts and "FY2022-23" in texts
    # the final answer used the same prompt contract: evidence blocks labelled E1..
    final_prompt = llm.requests["final"][0].messages[-1].content
    assert "[E1]" in final_prompt and "[E2]" in final_prompt
    # the agent's own notes are not passed to the final answer
    assert "Ready: E1, E2" not in final_prompt


def test_numeric_question_uses_calculate_and_the_verifier_passes(llm, make_graph) -> None:  # type: ignore[no-untyped-def]
    make_graph(TXN, raw_result([]))
    llm.agent = [
        tool_turn(("neighbors", {"entity_id": "C:TATASTEEL", "rel_types": ["PARTY_TO"]})),
        tool_turn(("calculate", {"expression": "48.20 + 12.50"})),
        stop_turn("Ready: E1, E2"),
    ]
    llm.final = [
        answer_json(
            "60.7",
            "The two transactions total 60.7 crore [E2], including 48.20 crore of sales [E1].",
            [("E2", "calculate(48.20 + 12.50) = 60.7")],
            "number",
        )
    ]
    llm.verifier = [verdict_json(("the total is 60.7", "SUPPORTED", ["E2"]))]

    result = AgentPipeline().answer(
        "What is the total of Tata Steel's related-party sales?", "req-num"
    )

    assert result.status == Status.OK and result.answer_short == "60.7"
    assert _tools(result) == ["neighbors", "calculate"]
    assert any(e.kind == "tool_result" and "= 60.7" in e.text for e in result.evidence)
    assert [s.name for s in result.trace if s.name == "verifier"] == ["verifier"]


def test_a_number_the_model_invents_fails_the_code_check_even_if_the_verifier_agrees(
    llm, make_graph
) -> None:  # type: ignore[no-untyped-def]
    make_graph(TXN, raw_result([]))
    llm.agent = [tool_turn(("calculate", {"expression": "48.20 + 12.50"})), stop_turn()]
    llm.final = [
        answer_json(
            "99",
            "The total is 99 crore [E1].",
            [("E1", "calculate(48.20 + 12.50) = 60.7")],
            "number",
        ),
        answer_json(
            "60.7",
            "The total is 60.7 crore [E1].",
            [("E1", "calculate(48.20 + 12.50) = 60.7")],
            "number",
        ),
    ]
    llm.verifier = [
        verdict_json(("the total is 99", "SUPPORTED", ["E1"])),  # lenient verifier model
        verdict_json(("the total is 60.7", "SUPPORTED", ["E1"])),
    ]
    llm.agent += [stop_turn("Ready: E1")]  # the repair cycle: nothing more to gather

    result = AgentPipeline().answer("Total?", "req-invented")

    assert result.answer_short == "60.7"
    assert any(s.name == "repair_cycle" for s in result.trace)


# --- verification and repair --------------------------------------------------


def _one_fact(llm, make_graph):  # type: ignore[no-untyped-def]
    make_graph(STEEL_FY24, raw_result([]))
    llm.agent = [
        board_call(),
        stop_turn("Ready: E1"),
    ]


def test_unsupported_claims_trigger_one_more_cycle_then_pass(llm, make_graph) -> None:  # type: ignore[no-untyped-def]
    _one_fact(llm, make_graph)
    llm.final = [
        sharma("Sharma chairs the audit committee [E1]."),
        sharma("Sharma is an independent director [E1]."),
    ]  # fmt: skip
    llm.verifier = [
        verdict_json(("Sharma chairs the audit committee", "UNSUPPORTED", [])),
        verdict_json(("Sharma is an independent director", "SUPPORTED", ["E1"])),
    ]
    llm.agent += [stop_turn("Ready: E1")]

    result = AgentPipeline().answer("Who is on the Tata Steel board?", "req-repair")

    assert result.status == Status.OK
    assert "audit committee" not in result.answer_long
    repair = next(s for s in result.trace if s.name == "repair_cycle")
    assert "audit committee" in repair.input_summary
    # the repair message was shown to the agent
    last_agent_request = llm.requests["agent"][-1]
    assert (
        "Verification failed for: Sharma chairs the audit committee"
        in last_agent_request.messages[-1].content
    )


def test_still_unsupported_claims_are_dropped_by_redrafting(llm, make_graph) -> None:  # type: ignore[no-untyped-def]
    _one_fact(llm, make_graph)
    mixed = verdict_json(
        ("Sharma is an independent director", "SUPPORTED", ["E1"]),
        ("Sharma chairs the audit committee", "UNSUPPORTED", []),
    )
    llm.final = [
        sharma("Sharma is independent and chairs audit [E1]."),
        sharma("Sharma is an independent director [E1]."),
        sharma("Sharma is an independent director [E1]."),
    ]  # fmt: skip
    llm.verifier = [mixed, mixed]
    llm.agent += [stop_turn("Ready: E1")]

    result = AgentPipeline().answer("Who is on the Tata Steel board?", "req-drop")

    assert result.status == Status.OK and "chairs" not in result.answer_long
    redraft_prompt = llm.requests["final"][-1].messages[-1].content
    assert "ONLY these supported claims" in redraft_prompt
    assert "Do not state: Sharma chairs the audit committee" in redraft_prompt
    assert any(s.name == "dropped_unsupported" for s in result.trace)


def test_nothing_supported_becomes_not_found(llm, make_graph) -> None:  # type: ignore[no-untyped-def]
    _one_fact(llm, make_graph)
    none = verdict_json(("a fabricated claim", "UNSUPPORTED", []))
    llm.final = [
        answer_json("X", "X is true [E1].", [("E1", "x")]),
        answer_json("X", "X is true [E1].", [("E1", "x")]),
    ]
    llm.verifier = [none, none]
    llm.agent += [stop_turn("Ready")]

    result = AgentPipeline().answer("Q?", "req-none")

    assert result.status == Status.ABSTAINED and result.answer_short == "not found in the data"


def test_a_failed_verifier_keeps_the_draft_and_is_traced(llm, make_graph) -> None:  # type: ignore[no-untyped-def]
    _one_fact(llm, make_graph)
    llm.final = [
        answer_json(
            "Anil Kumar Sharma",
            "Sharma [E1].",
            [("E1", SHARMA)],
        )
    ]
    llm.verifier = [ConnectionError("verifier down")]

    result = AgentPipeline().answer("Who?", "req-vfail")

    assert result.status == Status.OK and result.answer_short == "Anil Kumar Sharma"
    verifier = next(s for s in result.trace if s.name == "verifier")
    assert verifier.error and verifier.error.startswith("verify_failed")


def test_an_abstaining_draft_is_not_verified(llm, make_graph) -> None:  # type: ignore[no-untyped-def]
    make_graph()
    llm.agent = [stop_turn("nothing found")]
    llm.final = [answer_json("not found in the data", "No evidence.", [], "not_found")]

    result = AgentPipeline().answer("What is the CEO's favourite colour?", "req-abstain")

    assert result.status == Status.ABSTAINED and llm.requests["verifier"] == []


def test_verification_can_be_switched_off(llm, make_graph) -> None:  # type: ignore[no-untyped-def]
    _one_fact(llm, make_graph)
    llm.final = [
        answer_json(
            "Anil Kumar Sharma",
            "Sharma [E1].",
            [("E1", SHARMA)],
        )
    ]
    result = AgentPipeline(AgentConfig(verify_enabled=False)).answer("Who?", "req-noverify")
    assert result.status == Status.OK and llm.requests["verifier"] == []


# --- budgets and failures -------------------------------------------------------


def test_budget_exceeded_keeps_its_status_with_a_partial_answer(llm, make_graph) -> None:  # type: ignore[no-untyped-def]
    make_graph(STEEL_FY24, raw_result([]))
    llm.agent = [
        board_call(),
        tool_turn(("calculate", {"expression": "1+1"})),
    ]
    llm.final = [
        answer_json(
            "Anil Kumar Sharma",
            "Sharma [E1].",
            [("E1", SHARMA)],
        )
    ]
    llm.verifier = [verdict_json(("Sharma is a director", "SUPPORTED", ["E1"]))]

    result = AgentPipeline(AgentConfig(max_steps=2)).answer("Who?", "req-budget")

    assert result.status == Status.BUDGET and result.answer_short == "Anil Kumar Sharma"
    assert any(s.name == "budget_exceeded" for s in result.trace)


def test_budget_exceeded_with_no_answer_is_an_abstention(llm, make_graph) -> None:  # type: ignore[no-untyped-def]
    make_graph()
    llm.agent = [tool_turn(("calculate", {"expression": "1+1"}))]
    llm.final = [answer_json("not found in the data", "Nothing.", [], "not_found")]

    result = AgentPipeline(AgentConfig(max_steps=1)).answer("Q?", "req-budget-nf")

    assert result.status == Status.ABSTAINED


def test_a_dead_llm_with_no_evidence_is_an_error_not_an_abstention(llm, make_graph) -> None:  # type: ignore[no-untyped-def]
    make_graph()
    llm.agent = [ConnectionError("network down")]
    result = AgentPipeline().answer("Q?", "req-dead")
    assert result.status == Status.ERROR
    assert "network down" in (result.trace[-1].error or "")


def test_an_llm_failure_after_gathering_evidence_still_answers(llm, make_graph) -> None:  # type: ignore[no-untyped-def]
    make_graph(STEEL_FY24, raw_result([]))
    llm.agent = [
        board_call(),
        ConnectionError("dropped"),
    ]
    llm.final = [
        answer_json(
            "Anil Kumar Sharma",
            "Sharma [E1].",
            [("E1", SHARMA)],
        )
    ]
    llm.verifier = [verdict_json(("Sharma is a director", "SUPPORTED", ["E1"]))]
    result = AgentPipeline().answer("Who?", "req-partial")
    assert result.status == Status.OK


def test_the_spend_cap_becomes_an_error_result(llm, make_graph) -> None:  # type: ignore[no-untyped-def]
    make_graph()
    llm.agent = [SpendCapExceeded("cap")]
    result = AgentPipeline().answer("Q?", "req-cap")
    assert result.status == Status.ERROR and result.trace[-1].error == "spend_cap"


def test_a_failing_final_answer_is_an_error_result(llm, make_graph) -> None:  # type: ignore[no-untyped-def]
    make_graph()
    llm.agent = [stop_turn()]
    llm.final = [LLMResponse(content="", tokens_in=1, tokens_out=0, error="bad request")]
    result = AgentPipeline().answer("Q?", "req-final-err")
    assert result.status == Status.ERROR


def test_a_graph_outage_is_recoverable_the_agent_falls_back_to_text(
    llm, make_graph, vector
) -> None:  # type: ignore[no-untyped-def]
    from server.graph.queries import GraphQueryError

    make_graph(GraphQueryError("down"), GraphQueryError("down"))
    vector([OUTAGE_CHUNK])
    llm.agent = [
        tool_turn(("neighbors", {"entity_id": "C:TATASTEEL"})),
        tool_turn(("search_text", {"query": "independent director Tata Steel"})),
        stop_turn("Ready: E1"),
    ]
    llm.final = [
        answer_json(
            "Anil Kumar Sharma",
            "Sharma [E1].",
            [("E1", "Anil Kumar Sharma is an independent director.")],
        )
    ]
    llm.verifier = [verdict_json(("Sharma is independent", "SUPPORTED", ["E1"]))]

    result = AgentPipeline().answer("Who is independent?", "req-outage")

    assert result.status == Status.OK
    assert any(
        s.name == "neighbors" and s.error for s in result.trace
    )  # the failure was visible to the model
    assert (result.citations[0].doc_id, result.citations[0].page) == (STEEL_DOC, 12)


def test_graph_query_is_dropped_after_two_failures_end_to_end(llm, make_graph) -> None:  # type: ignore[no-untyped-def]
    make_graph()

    def bad(i: int) -> tuple[str, dict]:
        params = {"company_ids": [f"x;{i}"]}
        return "graph_query", {"query_name": "shared_directors", "params": params}

    llm.agent = [tool_turn(bad(1)), tool_turn(bad(2)), stop_turn("Ready")]
    llm.final = [answer_json("not found in the data", "None.", [], "not_found")]

    AgentPipeline().answer("Q?", "req-gq")

    offered = [[t.name for t in r.tools] for r in llm.requests["agent"]]
    assert "graph_query" in offered[1] and "graph_query" not in offered[2]


def test_agent_is_registered_with_the_other_pipelines() -> None:
    from server.pipelines.base import REGISTRY, load_all

    load_all()
    assert {"rag", "graphrag", "agent"} <= set(REGISTRY)


def test_final_answer_receives_evidence_within_the_shared_budget(
    llm, make_graph, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    from server.pipelines.agent import pipeline as pipe_mod

    big = raw_result(
        [
            __import__("tests.unit.graphrag_fixtures", fromlist=["director"]).director(
                f"P:{i}", "C:TATASTEEL", "FY2023-24", f"d{i}", quote="word " * 400
            )
            for i in range(10)
        ]
    )
    make_graph(big, raw_result([]))
    monkeypatch.setattr(pipe_mod.RETRIEVAL, "evidence_token_budget", 600)
    llm.agent = [
        tool_turn(("neighbors", {"entity_id": "C:TATASTEEL", "limit": 10})),
        stop_turn("Ready: E10"),
    ]
    llm.final = [answer_json("x", "x [E1].", [("E1", "q")])]
    llm.verifier = [verdict_json(("x", "SUPPORTED", ["E1"]))]

    result = AgentPipeline().answer("Who?", "req-fit")

    from server.parse.tokens import estimate_tokens
    from server.pipelines.common.budget import LABEL_OVERHEAD_TOKENS

    used = sum(estimate_tokens(e.text) + LABEL_OVERHEAD_TOKENS for e in result.evidence)
    assert used <= 600 and 0 < len(result.evidence) < 10
