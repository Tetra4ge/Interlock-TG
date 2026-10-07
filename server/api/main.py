"""The thin HTTP layer: validate input, call a pipeline or read the run store, return
typed JSON. No business logic lives here."""

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response

from server.api import demo, documents, quality, review, runs, subgraph
from server.api.deps import AppContext
from server.api.live import new_request_id, run_compare, run_one
from server.api.schemas import (
    PIPELINE_NAMES,
    AskIn,
    CompareIn,
    CompareOut,
    CompareRunsOut,
    DataQualityOut,
    DocumentPage,
    ExampleQuestion,
    HealthOut,
    QuestionOut,
    ResultOut,
    ReviewItem,
    RunMetrics,
    RunOut,
    SubgraphOut,
)
from server.pipelines.models import AnswerResult
from server.settings import settings

logger = logging.getLogger(__name__)

NEEDS_KEY = (
    "Live questions need an API key (GROQ_API_KEY). This question is not one of the cached "
    "examples; try one of the example questions."
)


def get_ctx(request: Request) -> AppContext:
    ctx: AppContext = request.app.state.ctx
    return ctx


def _bad_question(question: object) -> str:
    try:
        return demo.validate_question(question)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


def create_app(ctx: AppContext | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.ctx = ctx or AppContext()
        yield
        app.state.ctx.close()

    app = FastAPI(title="Interlock API", lifespan=lifespan)

    # Added before CORS so CORS is outermost: an unhandled error still returns JSON that the
    # browser is allowed to read, instead of a bare 500 it reports as a CORS failure.
    @app.middleware("http")
    async def json_errors(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        try:
            return await call_next(request)
        except Exception:
            logger.exception(f"unhandled error on {request.method} {request.url.path}")
            return JSONResponse({"detail": "internal server error"}, status_code=500)

    cfg = ctx.settings if ctx else settings
    origins = [o.strip() for o in cfg.cors_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware, allow_origins=origins, allow_credentials=True,
        allow_methods=["*"], allow_headers=["*"],
    )  # fmt: skip

    @app.get("/health", response_model=HealthOut)
    def health(request: Request) -> HealthOut:
        c = get_ctx(request)
        return HealthOut(
            tigergraph=c.tigergraph_ok(), turso=c.turso_ok(), llm_key=c.llm_key,
            demo_mode=c.demo_mode, llm_offline=c.settings.llm_offline,
        )  # fmt: skip

    # ---- live answers -------------------------------------------------------------

    @app.post("/ask", response_model=AnswerResult)
    def ask(body: AskIn, request: Request) -> AnswerResult:
        c = get_ctx(request)
        if body.pipeline not in PIPELINE_NAMES:
            raise HTTPException(
                400, f"unknown pipeline {body.pipeline!r}; choose one of {list(PIPELINE_NAMES)}"
            )
        question = _bad_question(body.question)
        if c.demo_mode:
            cached = demo.lookup(c.cached_answers_path, question)
            if cached and body.pipeline in cached:
                return cached[body.pipeline]
        if not c.llm_key:
            raise HTTPException(503, NEEDS_KEY)
        return run_one(c, body.pipeline, question, new_request_id())

    @app.post("/compare", response_model=CompareOut)
    async def compare(body: CompareIn, request: Request) -> CompareOut:
        c = get_ctx(request)
        question = _bad_question(body.question)
        rid = new_request_id()
        if c.demo_mode:
            cached = demo.lookup(c.cached_answers_path, question)
            if cached:
                return CompareOut(request_id=rid, results=cached, cached=True)
        if not c.llm_key:
            raise HTTPException(503, NEEDS_KEY)
        return CompareOut(request_id=rid, results=await run_compare(c, question, rid))

    @app.get("/examples", response_model=list[ExampleQuestion])
    def example_questions(request: Request) -> list[ExampleQuestion]:
        return demo.examples(get_ctx(request).cached_answers_path)

    # ---- run store (read-only) ----------------------------------------------------

    @app.get("/runs", response_model=list[RunOut])
    def list_runs(request: Request) -> list[RunOut]:
        with get_ctx(request).db() as conn:
            return runs.list_runs(conn)

    @app.get("/runs/{run_id}/metrics", response_model=RunMetrics)
    def run_metrics(run_id: str, request: Request) -> RunMetrics:
        with get_ctx(request).db() as conn:
            found = runs.run_metrics(conn, run_id)
        if found is None:
            raise HTTPException(404, f"no scored run {run_id!r}")
        return found

    @app.get("/runs/{run_id}/results/{qid}", response_model=ResultOut)
    def run_result(run_id: str, qid: str, request: Request) -> ResultOut:
        with get_ctx(request).db() as conn:
            found = runs.get_result(conn, run_id, qid)
        if found is None:
            raise HTTPException(404, f"no result for {qid!r} in run {run_id!r}")
        return found

    @app.get("/compare-runs", response_model=CompareRunsOut)
    def compare_runs(
        request: Request,
        rag: str | None = None,
        graphrag: str | None = None,
        agent: str | None = None,
    ) -> CompareRunsOut:
        chosen = {k: v for k, v in (("rag", rag), ("graphrag", graphrag), ("agent", agent)) if v}
        if not chosen:
            raise HTTPException(400, "give at least one of rag, graphrag, agent as a run_id")
        with get_ctx(request).db() as conn:
            out = runs.compare_view(conn, chosen)
        if not out.metrics:
            raise HTTPException(404, "none of those runs has scored results")
        return out

    @app.get("/questions", response_model=list[QuestionOut])
    def questions(
        request: Request, split: str | None = Query(None, pattern="^(dev|test)$"),
        include_gold: bool = False,
    ) -> list[QuestionOut]:  # fmt: skip
        with get_ctx(request).db() as conn:
            return runs.list_questions(conn, split, include_gold)

    @app.get("/graph/subgraph", response_model=SubgraphOut)
    def graph_subgraph(edge_ids: str, request: Request) -> SubgraphOut:
        try:
            ids = subgraph.parse_edge_ids(edge_ids)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        try:
            return subgraph.fetch_subgraph(ids)
        except subgraph.SubgraphUnavailable as e:
            raise HTTPException(503, f"The graph is not reachable right now ({e}).") from e

    @app.get("/data-quality", response_model=DataQualityOut)
    def data_quality(request: Request) -> DataQualityOut:
        with get_ctx(request).db() as conn:
            return quality.data_quality(conn)

    @app.get("/documents/{doc_id}/pages/{page}", response_model=DocumentPage)
    def document_page(doc_id: str, page: int, request: Request) -> DocumentPage:
        try:
            with get_ctx(request).db() as conn:
                return documents.page_text(conn, doc_id, page)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        except documents.DocumentNotFound as e:
            raise HTTPException(404, str(e)) from e

    @app.get("/documents/{doc_id}/pdf")
    def document_pdf(doc_id: str) -> FileResponse:
        path = documents.pdf_path(doc_id)
        if path is None:
            raise HTTPException(404, "the source PDF is not available in this checkout")
        return FileResponse(path, media_type="application/pdf", content_disposition_type="inline")

    @app.get("/review-queue", response_model=list[ReviewItem])
    def review_queue(request: Request, limit: int = Query(100, ge=1, le=500)) -> list[ReviewItem]:
        with get_ctx(request).db() as conn:
            return review.pending_reviews(conn, limit)

    return app


app = create_app()
