"""A self-contained API for demonstrating and browser-testing the dashboard's graph views.

It serves a seeded in-memory run store with one multi-hop question answered by RAG,
GraphRAG and the agent, and stubs the TigerGraph subgraph query, so it needs no database,
no graph and no LLM key. It never touches the real run store.

    uv run python -m tests.e2e.fixture_server            # http://127.0.0.1:8001
    CORS_ORIGINS=http://localhost:3001 uv run python -m tests.e2e.fixture_server
"""

import os

import uvicorn

from server.api import subgraph as subgraph_mod
from server.api.deps import AppContext
from server.api.main import create_app
from server.pipelines.models import (
    AnswerResult,
    AnswerType,
    Citation,
    EvidenceItem,
    Status,
    TraceStep,
    Usage,
)
from server.settings import Settings
from tests.conftest import MemoryDB
from tests.unit.api_fixtures import seed_question, seed_run
from tests.unit.graphrag_fixtures import director, raw_result

STEEL_DOC, MOTORS_DOC = "a" * 64, "b" * 64
QID = "FX-MH-0001"
QUESTION = "Which independent director of Tata Steel also sits on the board of Tata Motors?"
ROLE = "Independent Director"
SHARMA_QUOTE = f"Anil Kumar Sharma | {ROLE}"

NAMES = {
    "C:TATASTEEL": ("Tata Steel Limited", "company"),
    "C:TATAMOTORS": ("Tata Motors Limited", "company"),
    "P:1": ("Anil Kumar Sharma", "person"),
    "P:2": ("Rajesh Verma", "person"),
}


def _edge(person: str, company: str, edge_id: str, doc: str, page: int, quote: str) -> dict:
    return director(person, company, "FY2023-24", edge_id, doc_id=doc, page=page, quote=quote)


EDGES = [
    _edge("P:1", "C:TATASTEEL", "d-steel-1", STEEL_DOC, 46, SHARMA_QUOTE),
    _edge("P:2", "C:TATASTEEL", "d-steel-2", STEEL_DOC, 46, f"Rajesh Verma | {ROLE}"),
    _edge("P:1", "C:TATAMOTORS", "d-motors-1", MOTORS_DOC, 12, SHARMA_QUOTE),
]


def _triple(
    edge_id: str, person: str, company: str, doc: str, page: int, quote: str
) -> EvidenceItem:
    text = (
        f"Person: {person} —[DIRECTOR_OF: {ROLE}; FY2023-24]→ Company: {company}\n"
        f'  source: doc {doc[:12]}…, p.{page} | quote: "{quote}"'
    )
    return EvidenceItem(kind="triple", ref_id=edge_id, text=text)


def _trace(pipeline: str, steps: int) -> list[TraceStep]:
    def kind(i: int) -> str:
        return "tool" if pipeline == "agent" and i % 2 else "retrieve"

    return [
        TraceStep(
            step=i + 1, kind=kind(i), name=f"step_{i + 1}", input_summary="", output_summary="ok"
        )
        for i in range(steps)
    ]


def _result(
    pipeline: str, short: str, status: Status, evidence: list[EvidenceItem], steps: int
) -> AnswerResult:
    is_agent = pipeline == "agent"
    citations = (
        [
            Citation(doc_id=STEEL_DOC, page=46, quote=SHARMA_QUOTE),
            Citation(doc_id=MOTORS_DOC, page=12, quote=SHARMA_QUOTE),
        ]
        if evidence
        else []
    )
    return AnswerResult(
        pipeline=pipeline,
        question=QUESTION,
        answer_short=short,
        answer_long=f"{short} sits on both boards [E1] [E2]." if evidence else "No evidence.",
        answer_type=AnswerType.ENTITY if short else AnswerType.NOT_FOUND,
        citations=citations,
        evidence=evidence,
        trace=_trace(pipeline, steps),
        usage=Usage(
            tokens_in=900,
            tokens_out=80,
            cost_usd=0.0,
            latency_ms=2000 * steps,
            llm_calls=5 if is_agent else 1,
            tool_calls=3 if is_agent else 0,
        ),  # fmt: skip
        status=status,
    )


def build_context() -> AppContext:
    db = MemoryDB()
    seed_question(
        db, QID, "multi_hop", "dev", QUESTION, gold="Anil Kumar Sharma",
        gold_evidence=[{"doc_id": STEEL_DOC, "page": 46}, {"doc_id": MOTORS_DOC, "page": 12}],
    )  # fmt: skip

    steel = _triple(
        "d-steel-1", "Anil Kumar Sharma", "Tata Steel Limited", STEEL_DOC, 46, SHARMA_QUOTE
    )
    motors = _triple(
        "d-motors-1", "Anil Kumar Sharma", "Tata Motors Limited", MOTORS_DOC, 12, SHARMA_QUOTE
    )
    other = _triple(
        "d-steel-2", "Rajesh Verma", "Tata Steel Limited", STEEL_DOC, 46, "Rajesh Verma"
    )
    sharma = "Anil Kumar Sharma"
    runs = {
        "fx-rag": ("rag", _result("rag", "", Status.ABSTAINED, [], 4), 0.0, "wrong_abstention"),
        "fx-graphrag": (
            "graphrag",
            _result("graphrag", sharma, Status.OK, [steel, motors, other], 9),
            1.0,
            None,
        ),
        "fx-agent": ("agent", _result("agent", sharma, Status.OK, [steel, motors], 13), 1.0, None),
    }
    for run_id, (pipeline, result, correct, label) in runs.items():
        row = {"result": result, "correct": correct, "failure_label": label}
        seed_run(db, run_id, pipeline, rows={QID: row})

    # The graph is stubbed with the shape the installed query returns; no TigerGraph needed.
    subgraph_mod.run_installed_strict = lambda name, params, timeout=None: raw_result(EDGES)  # type: ignore[assignment]
    subgraph_mod.entity_names = lambda ids: {i: NAMES[i] for i in ids if i in NAMES}  # type: ignore[assignment]

    cors = os.environ.get("CORS_ORIGINS", "http://localhost:3001")
    return AppContext(
        cfg=Settings(groq_api_key="", demo_mode=True, read_cache_seconds=0, cors_origins=cors),
        db_factory=lambda: db,
        tg_probe=lambda: True,
    )


if __name__ == "__main__":
    uvicorn.run(
        create_app(build_context()), host="127.0.0.1", port=int(os.environ.get("PORT", "8001"))
    )
