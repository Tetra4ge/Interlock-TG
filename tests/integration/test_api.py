"""The HTTP API end to end through FastAPI's TestClient.

The database is a real SQLite store with the project migrations; the pipelines are
fakes and TigerGraph is stubbed, so no network, LLM or ML model is used."""

import json
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.api import live as live_mod
from server.api import subgraph as sg
from server.api.deps import ADHOC_RUN_ID, AppContext
from server.api.main import create_app
from server.graph.queries import GraphQueryError
from server.pipelines.models import AnswerResult, Status
from server.settings import Settings
from tests.conftest import MemoryDB
from tests.unit.api_fixtures import answer_result, seed_question, seed_run
from tests.unit.graphrag_fixtures import director, raw_result

ORIGIN = "http://localhost:3000"


class FakePipeline:
    def __init__(self, name: str, short: str = "an answer", raises: Exception | None = None,
                 delay: float = 0.0, status: Status = Status.OK) -> None:  # fmt: skip
        self.name, self.short, self.raises, self.delay, self.status = (
            name,
            short,
            raises,
            delay,
            status,
        )
        self.calls: list[tuple[str, str]] = []

    def answer(self, question: str, request_id: str) -> AnswerResult:
        self.calls.append((question, request_id))
        if self.delay:
            time.sleep(self.delay)
        if self.raises:
            raise self.raises
        return answer_result(self.name, self.short, self.status, question=question, cost=0.01)


class Harness:
    def __init__(
        self, memdb: MemoryDB, tmp_path: Path, key: str = "key", demo: bool = False
    ) -> None:
        self.pipes = {n: FakePipeline(n, f"{n} answer") for n in ("rag", "graphrag", "agent")}
        self.loads = 0
        self.cache = tmp_path / "cached.jsonl"
        self.tg_ok = True

        def loader() -> dict:
            self.loads += 1
            return self.pipes

        self.ctx = AppContext(
            cfg=Settings(groq_api_key=key, demo_mode=demo, cors_origins=ORIGIN),
            db_factory=lambda: memdb,
            pipelines_loader=loader,
            tg_probe=lambda: self.tg_ok,
            cached_answers_path=self.cache,
        )
        self.client_cm = TestClient(create_app(self.ctx), raise_server_exceptions=False)

    def __enter__(self) -> TestClient:
        return self.client_cm.__enter__()

    def __exit__(self, *a: object) -> None:
        self.client_cm.__exit__(*a)

    def write_cache(self, question: str, **pipelines: str) -> None:
        entry = {
            "question": question,
            "results": {
                p: answer_result(p, s).model_dump(mode="json") for p, s in pipelines.items()
            },
            "source_runs": {p: f"run-{p}" for p in pipelines},
        }
        self.cache.write_text(json.dumps(entry) + "\n")


@pytest.fixture
def harness(memdb: MemoryDB, tmp_path: Path) -> Harness:
    return Harness(memdb, tmp_path)


# --- health ------------------------------------------------------------------------


def test_health_reports_booleans(harness: Harness) -> None:
    with harness as client:
        r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {
        "tigergraph": True,
        "turso": True,
        "llm_key": True,
        "demo_mode": False,
        "llm_offline": False,
    }


def test_health_still_answers_when_tigergraph_is_down(harness: Harness) -> None:
    harness.tg_ok = False
    with harness as client:
        body = client.get("/health").json()
    assert body["tigergraph"] is False and body["turso"] is True


def test_health_without_a_key_reports_demo_mode(memdb: MemoryDB, tmp_path: Path) -> None:
    with Harness(memdb, tmp_path, key="") as client:
        body = client.get("/health").json()
    assert body["llm_key"] is False and body["demo_mode"] is True


# --- /ask --------------------------------------------------------------------------


def test_ask_runs_the_named_pipeline(harness: Harness) -> None:
    with harness as client:
        r = client.post("/ask", json={"question": "Who audits Tata Steel?", "pipeline": "rag"})
    assert r.status_code == 200
    assert r.json()["pipeline"] == "rag" and r.json()["answer_short"] == "rag answer"
    assert len(harness.pipes["rag"].calls) == 1 and harness.pipes["agent"].calls == []


def test_ask_unknown_pipeline_is_400(harness: Harness) -> None:
    with harness as client:
        r = client.post("/ask", json={"question": "q", "pipeline": "magic"})
    assert r.status_code == 400 and "unknown pipeline" in r.json()["detail"]
    assert harness.loads == 0  # rejected before any pipeline was loaded


@pytest.mark.parametrize("question", ["", "   ", "\x00\x01", "x" * 2000, "x" * 501])
def test_ask_rejects_empty_or_overlong_questions(harness: Harness, question: str) -> None:
    with harness as client:
        r = client.post("/ask", json={"question": question, "pipeline": "rag"})
    assert r.status_code == 400
    assert harness.pipes["rag"].calls == []


def test_ask_accepts_a_500_character_question(harness: Harness) -> None:
    with harness as client:
        assert (
            client.post("/ask", json={"question": "x" * 500, "pipeline": "rag"}).status_code == 200
        )


def test_ask_cleans_the_question_before_use(harness: Harness) -> None:
    with harness as client:
        client.post(
            "/ask", json={"question": "  Who\x00 audits\n  Tata Steel? ", "pipeline": "rag"}
        )
    assert harness.pipes["rag"].calls[0][0] == "Who audits Tata Steel?"


@pytest.mark.parametrize(
    "body", [{}, {"question": "q"}, {"pipeline": "rag"}, {"question": 5, "pipeline": "rag"}]
)
def test_ask_malformed_bodies_are_422(harness: Harness, body: dict) -> None:
    with harness as client:
        assert client.post("/ask", json=body).status_code == 422


def test_ask_saves_the_answer_for_later_inspection(harness: Harness, memdb: MemoryDB) -> None:
    with harness as client:
        client.post("/ask", json={"question": "q", "pipeline": "rag"})
    row = memdb.execute("SELECT run_id, qid FROM results").fetchone()
    assert row[0] == ADHOC_RUN_ID and row[1].endswith(":rag")


def test_ask_without_a_key_and_not_cached_is_503(memdb: MemoryDB, tmp_path: Path) -> None:
    with Harness(memdb, tmp_path, key="") as client:
        r = client.post("/ask", json={"question": "something new", "pipeline": "rag"})
    assert r.status_code == 503 and "API key" in r.json()["detail"]


def test_ask_in_demo_mode_serves_the_cached_pipeline_without_running_it(
    memdb: MemoryDB, tmp_path: Path
) -> None:
    h = Harness(memdb, tmp_path, key="", demo=True)
    h.write_cache("Who audits Tata Steel?", rag="PwC cached")
    with h as client:
        r = client.post("/ask", json={"question": "who audits tata steel", "pipeline": "rag"})
    assert r.status_code == 200 and r.json()["answer_short"] == "PwC cached"
    assert h.loads == 0 and h.pipes["rag"].calls == []


# --- /compare ----------------------------------------------------------------------


def test_compare_runs_all_three_and_returns_each(harness: Harness) -> None:
    with harness as client:
        r = client.post("/compare", json={"question": "Who audits Tata Steel?"})
    body = r.json()
    assert r.status_code == 200 and body["cached"] is False and body["request_id"]
    assert set(body["results"]) == {"rag", "graphrag", "agent"}
    assert all(res["status"] == "ok" for res in body["results"].values())
    assert {p.calls[0][1] for p in harness.pipes.values()} == {body["request_id"]}  # one shared id


def test_compare_with_one_pipeline_raising_still_returns_the_others(harness: Harness) -> None:
    harness.pipes["graphrag"].raises = RuntimeError("graph exploded")
    with harness as client:
        r = client.post("/compare", json={"question": "q"})
    results = r.json()["results"]
    assert r.status_code == 200
    assert results["graphrag"]["status"] == "error"
    assert "graph exploded" in results["graphrag"]["trace"][-1]["error"]
    assert results["rag"]["status"] == "ok" and results["agent"]["status"] == "ok"


def test_compare_with_an_unavailable_pipeline_marks_only_that_one(harness: Harness) -> None:
    del harness.pipes["agent"]
    with harness as client:
        results = client.post("/compare", json={"question": "q"}).json()["results"]
    assert (
        results["agent"]["status"] == "error"
        and "not available" in results["agent"]["trace"][-1]["error"]
    )
    assert results["rag"]["status"] == "ok"


def test_compare_runs_the_pipelines_concurrently(harness: Harness) -> None:
    for p in harness.pipes.values():
        p.delay = 0.3
    with harness as client:
        started = time.monotonic()
        r = client.post("/compare", json={"question": "q"})
        elapsed = time.monotonic() - started
    assert r.status_code == 200 and elapsed < 0.8  # three 0.3s pipelines in parallel, not 0.9s


def test_compare_times_out_a_hung_pipeline_without_hurting_the_others(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = threading.Event()
    harness.pipes["agent"].answer = lambda q, rid: (release.wait(5), answer_result("agent"))[1]  # type: ignore[method-assign]
    monkeypatch.setattr(live_mod, "PIPELINE_TIMEOUT_S", 0.2)
    with harness as client:
        results = client.post("/compare", json={"question": "q"}).json()["results"]
    release.set()
    assert (
        results["agent"]["status"] == "error"
        and "timed out" in results["agent"]["trace"][-1]["error"]
    )
    assert results["rag"]["status"] == "ok"


def test_compare_rejects_bad_questions(harness: Harness) -> None:
    with harness as client:
        assert client.post("/compare", json={"question": ""}).status_code == 400
        assert client.post("/compare", json={"question": "x" * 2000}).status_code == 400
    assert all(p.calls == [] for p in harness.pipes.values())


def test_compare_in_demo_mode_returns_the_cached_answers_with_no_llm_call(
    memdb: MemoryDB, tmp_path: Path
) -> None:
    h = Harness(memdb, tmp_path, key="", demo=True)
    h.write_cache("Which director sits on two Tata boards?", rag="r", graphrag="g", agent="a")
    with h as client:
        r = client.post("/compare", json={"question": "Which director sits on two Tata boards?"})
    body = r.json()
    assert r.status_code == 200 and body["cached"] is True
    assert {k: v["answer_short"] for k, v in body["results"].items()} == {
        "rag": "r",
        "graphrag": "g",
        "agent": "a",
    }
    assert h.loads == 0 and all(p.calls == [] for p in h.pipes.values())


def test_compare_in_demo_mode_with_an_unknown_question_and_no_key_is_503(
    memdb: MemoryDB, tmp_path: Path
) -> None:
    h = Harness(memdb, tmp_path, key="", demo=True)
    h.write_cache("a cached one", rag="r")
    with h as client:
        r = client.post("/compare", json={"question": "something else"})
    assert r.status_code == 503
    assert "example questions" in r.json()["detail"] and "API key" in r.json()["detail"]


def test_compare_in_demo_mode_with_a_key_falls_through_to_live_for_uncached_questions(
    memdb: MemoryDB, tmp_path: Path
) -> None:
    h = Harness(memdb, tmp_path, key="key", demo=True)
    with h as client:
        r = client.post("/compare", json={"question": "never cached"})
    assert r.status_code == 200 and r.json()["cached"] is False and h.loads == 1


def test_examples_lists_cached_questions(memdb: MemoryDB, tmp_path: Path) -> None:
    h = Harness(memdb, tmp_path)
    h.write_cache("Q one", rag="a", agent="b")
    with h as client:
        body = client.get("/examples").json()
    assert body == [{"question": "Q one", "pipelines": ["agent", "rag"]}]


# --- run store -------------------------------------------------------------------------


@pytest.fixture
def seeded(harness: Harness, memdb: MemoryDB) -> Harness:
    seed_question(memdb, "q1", "single_fact", split="dev")
    seed_question(memdb, "q2", "single_fact", split="dev")
    seed_question(memdb, "t1", "numerical", split="test", gold="secret")

    def row(correct: float, label: str | None = None) -> dict:
        result = answer_result(cost=0.02, latency_ms=100)
        return {"result": result, "correct": correct, "failure_label": label}

    seed_run(memdb, "run-rag", "rag", rows={"q1": row(1.0), "q2": row(0.0, "retrieval_miss")})
    seed_run(memdb, "run-agent", "agent", rows={"q1": row(1.0), "q2": row(1.0)})
    return harness


def test_runs_lists_stored_runs(seeded: Harness) -> None:
    with seeded as client:
        runs = client.get("/runs").json()
    assert {r["run_id"] for r in runs} == {"run-rag", "run-agent"}
    assert next(r for r in runs if r["run_id"] == "run-rag")["n_results"] == 2


def test_metrics_numbers_match_the_scores(seeded: Harness, memdb: MemoryDB) -> None:
    with seeded as client:
        body = client.get("/runs/run-rag/metrics").json()
    scores = [
        r[0]
        for r in memdb.execute("SELECT correct FROM scores WHERE run_id = 'run-rag'").fetchall()
    ]
    assert body["overall"]["n"] == 2
    assert body["overall"]["correct_mean"] == pytest.approx(sum(scores) / len(scores))
    assert body["overall"]["failures"] == {"retrieval_miss": 1}
    assert body["overall"]["cost_usd_mean"] == pytest.approx(0.02)
    assert body["by_category"]["single_fact"]["n"] == 2


def test_metrics_for_an_unknown_run_is_404(seeded: Harness) -> None:
    with seeded as client:
        assert client.get("/runs/nope/metrics").status_code == 404


def test_a_single_result_comes_with_its_score(seeded: Harness) -> None:
    with seeded as client:
        body = client.get("/runs/run-rag/results/q2").json()
        missing = client.get("/runs/run-rag/results/zzz")
    assert body["score"]["failure_label"] == "retrieval_miss" and body["question"] == "question q2"
    assert missing.status_code == 404


def test_compare_runs_joins_runs_and_reports_pairs(seeded: Harness) -> None:
    with seeded as client:
        body = client.get("/compare-runs", params={"rag": "run-rag", "agent": "run-agent"}).json()
    assert [q["qid"] for q in body["questions"]] == ["q1", "q2"]
    assert body["questions"][1]["cells"]["rag"]["failure_label"] == "retrieval_miss"
    assert body["questions"][1]["cells"]["agent"]["correct"] == 1.0
    assert body["pairs"][0]["a"] == "agent" and body["pairs"][0]["b"] == "rag"
    assert body["leaders"]["overall"]["pipeline"] == "agent"


def test_compare_runs_needs_at_least_one_run(seeded: Harness) -> None:
    with seeded as client:
        assert client.get("/compare-runs").status_code == 400
        assert client.get("/compare-runs", params={"rag": "nope"}).status_code == 404


def test_questions_hide_test_gold_unless_asked(seeded: Harness) -> None:
    with seeded as client:
        by_id = {q["qid"]: q for q in client.get("/questions").json()}
        shown = {
            q["qid"]: q for q in client.get("/questions", params={"include_gold": "true"}).json()
        }
        test_only = client.get("/questions", params={"split": "test"}).json()
        bad = client.get("/questions", params={"split": "prod"})
    assert by_id["q1"]["gold_answer"] == "gold" and by_id["t1"]["gold_answer"] is None
    assert shown["t1"]["gold_answer"] == "secret"
    assert [q["qid"] for q in test_only] == ["t1"] and bad.status_code == 422


def test_data_quality_returns_counts(seeded: Harness) -> None:
    with seeded as client:
        body = client.get("/data-quality").json()
    assert body["documents"] == 0 and "note" in body and body["provenance_complete_pct"] is None


# --- subgraph --------------------------------------------------------------------------


def test_subgraph_returns_only_the_requested_edges(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = raw_result([
        director("P:1", "C:TATASTEEL", "FY2023-24", "d1"),
        director("P:2", "C:TATASTEEL", "FY2023-24", "d2"),
    ])  # fmt: skip
    monkeypatch.setattr(sg, "run_installed_strict", lambda name, params, timeout=None: raw)
    monkeypatch.setattr(sg, "entity_names", lambda ids: {})
    with harness as client:
        body = client.get("/graph/subgraph", params={"edge_ids": "d1"}).json()
    assert [e["id"] for e in body["edges"]] == ["d1"] and {n["id"] for n in body["nodes"]} == {
        "P:1",
        "C:TATASTEEL",
    }


@pytest.mark.parametrize("ids", ["", 'a"; DROP', "x" * 65, ",".join(f"e{i}" for i in range(101))])
def test_subgraph_rejects_bad_ids(harness: Harness, ids: str) -> None:
    with harness as client:
        assert client.get("/graph/subgraph", params={"edge_ids": ids}).status_code == 400


def test_subgraph_reports_an_unreachable_graph_as_503(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    def down(name: str, params: dict, timeout: int | None = None) -> object:
        raise GraphQueryError("subgraph_by_edges: 404 Not Found")

    monkeypatch.setattr(sg, "run_installed_strict", down)
    with harness as client:
        r = client.get("/graph/subgraph", params={"edge_ids": "d1"})
    assert r.status_code == 503 and "not reachable" in r.json()["detail"]


# --- cross-cutting -----------------------------------------------------------------------


def test_cors_allows_the_dashboard_origin_and_only_that(harness: Harness) -> None:
    with harness as client:
        ok = client.get("/health", headers={"Origin": ORIGIN})
        other = client.get("/health", headers={"Origin": "http://evil.example"})
        preflight = client.options(
            "/compare", headers={"Origin": ORIGIN, "Access-Control-Request-Method": "POST"}
        )
    assert ok.headers["access-control-allow-origin"] == ORIGIN
    assert "access-control-allow-origin" not in other.headers
    assert (
        preflight.status_code == 200 and preflight.headers["access-control-allow-origin"] == ORIGIN
    )


def test_an_unexpected_error_is_json_with_cors_headers(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(conn: object) -> None:
        raise RuntimeError("secret internals")

    monkeypatch.setattr("server.api.main.runs.list_runs", boom)
    with harness as client:
        r = client.get("/runs", headers={"Origin": ORIGIN})
    assert r.status_code == 500 and r.json() == {"detail": "internal server error"}
    assert "secret internals" not in r.text
    assert r.headers["access-control-allow-origin"] == ORIGIN


def test_the_openapi_schema_is_served(harness: Harness) -> None:
    with harness as client:
        spec = client.get("/openapi.json").json()
    assert {"/health", "/ask", "/compare", "/runs", "/compare-runs", "/graph/subgraph"} <= set(
        spec["paths"]
    )


def test_review_queue_route_lists_pending_records(harness: Harness, memdb: MemoryDB) -> None:
    memdb.execute(
        "INSERT INTO documents (doc_id, company_id, doc_type, fiscal_year, file_path, fetched_at) "
        "VALUES ('d', 'TATASTEEL', 'annual_report', 'FY2023-24', 'x.pdf', 'now')"
    )
    memdb.execute(
        "INSERT INTO records (record_id, run_id, doc_id, record_type, payload_json, status) "
        "VALUES ('r1', 'run', 'd', 'rpt', '{\"amount_raw\": \"48.2\"}', 'review')"
    )
    memdb.execute(
        "INSERT INTO review_queue (record_id, reason, created_at) "
        "VALUES ('r1', 'unit_unknown', 'now')"
    )
    memdb.commit()
    with harness as client:
        body = client.get("/review-queue").json()
        too_many = client.get("/review-queue", params={"limit": 9999})
    assert body[0]["record_id"] == "r1" and body[0]["payload"] == {"amount_raw": "48.2"}
    assert too_many.status_code == 422


def test_document_routes(harness: Harness, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from server.api import documents as docs

    doc = "c" * 64
    parsed, raw = tmp_path / "parsed", tmp_path / "raw"
    parsed.mkdir()
    raw.mkdir()
    (parsed / f"{doc}.json").write_text(
        json.dumps({"pages": [{"page_no": 3, "text": "Page three text"}]})
    )
    (raw / f"{doc}.pdf").write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(docs, "PARSED_DIR", parsed)
    monkeypatch.setattr(docs, "RAW_DIR", raw)
    with harness as client:
        ok = client.get(f"/documents/{doc}/pages/3")
        no_page = client.get(f"/documents/{doc}/pages/99")
        bad_id = client.get("/documents/not-an-id/pages/1")
        bad_page = client.get(f"/documents/{doc}/pages/0")
        pdf = client.get(f"/documents/{doc}/pdf")
        no_pdf = client.get(f"/documents/{'d' * 64}/pdf")
        traversal = client.get("/documents/..%2F..%2Fetc%2Fpasswd/pdf")
    assert (
        ok.status_code == 200
        and ok.json()["text"] == "Page three text"
        and ok.json()["pdf_available"] is True
    )
    assert no_page.status_code == 404 and bad_id.status_code == 400 and bad_page.status_code == 400
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")
    assert no_pdf.status_code == 404 and "not available" in no_pdf.json()["detail"]
    assert traversal.status_code in (404, 422)
