import time

from server.graph.queries import vector_search
from server.llm.gateway import SpendCapExceeded
from server.pipelines.base import register
from server.pipelines.common.answer import final_answer
from server.pipelines.common.budget import fit_to_budget
from server.pipelines.common.citations import validate_citations
from server.pipelines.common.render import assign_labels
from server.pipelines.common.rerank import rerank
from server.pipelines.common.tracer import Tracer
from server.pipelines.config import RETRIEVAL
from server.pipelines.models import AnswerResult, AnswerType, EvidenceItem, Status
from server.store.db import connect


def _excluded_doc_ids() -> set[str]:
    conn = connect()
    try:
        rows = conn.execute("SELECT doc_id FROM documents WHERE status = 'excluded'").fetchall()
    finally:
        conn.close()
    return {r[0] for r in rows}


class RAGPipeline:
    name = "rag"

    def answer(self, question: str, request_id: str) -> AnswerResult:
        tr = Tracer(request_id, self.name)
        start = time.perf_counter()

        try:
            hits = self._retrieve(question, tr)

            provenance = {
                h["chunk_id"]: {
                    "doc_id": h.get("doc_id", ""),
                    "page_start": h.get("page_start", 0),
                    "page_end": h.get("page_end", 0),
                    "section": h.get("section", ""),
                    "fiscal_year": h.get("fiscal_year", ""),
                }
                for h in hits
            }
            items = [
                EvidenceItem(kind="chunk", ref_id=h["chunk_id"], text=h.get("text", ""))
                for h in hits
            ]
            items = fit_to_budget(items, RETRIEVAL.evidence_token_budget)
            labels = assign_labels(items, provenance)

            model_answer, err = final_answer(tr, question, labels)
            if model_answer is None:
                return self._error_result(question, tr, err or "unknown_error", start)

            citations, flags = validate_citations(model_answer.citations, labels)
            tr.add(
                "verify",
                "validate_citations",
                f"{len(model_answer.citations)} citations",
                str(flags),
            )

            status = (
                Status.ABSTAINED if model_answer.answer_type == AnswerType.NOT_FOUND else Status.OK
            )
            return AnswerResult(
                pipeline=self.name,
                question=question,
                answer_short=model_answer.answer_short,
                answer_long=model_answer.answer_long,
                answer_type=model_answer.answer_type,
                citations=citations,
                evidence=[le.item for le in labels.values()],
                trace=tr.steps,
                usage=tr.usage(self._elapsed_ms(start)),
                status=status,
            )
        except Exception as e:
            reason = "spend_cap" if isinstance(e, SpendCapExceeded) else repr(e)
            return self._error_result(question, tr, reason, start)

    def _retrieve(self, question: str, tr: Tracer) -> list[dict]:
        t0 = time.perf_counter()
        excluded = _excluded_doc_ids()
        hits = [
            h
            for h in vector_search(question, k=RETRIEVAL.rag_top_k)
            if h.get("doc_id") not in excluded
        ]
        tr.add(
            "retrieve",
            "vector_search",
            f"k={RETRIEVAL.rag_top_k}",
            ", ".join(h.get("chunk_id", "") for h in hits[:10]),
            latency_ms=self._elapsed_ms(t0),
        )

        if RETRIEVAL.use_reranker:
            t1 = time.perf_counter()
            hits = rerank(question, hits)[: RETRIEVAL.rerank_top_k]
            tr.add(
                "retrieve",
                "rerank",
                f"top_k={RETRIEVAL.rerank_top_k}",
                ", ".join(h.get("chunk_id", "") for h in hits[:10]),
                latency_ms=self._elapsed_ms(t1),
            )
        return hits

    @staticmethod
    def _elapsed_ms(start: float) -> int:
        return int((time.perf_counter() - start) * 1000)

    def _error_result(self, question: str, tr: Tracer, error: str, start: float) -> AnswerResult:
        if not tr.steps or tr.steps[-1].error != error:
            tr.add("verify", "error", question, "", error=error)
        return AnswerResult(
            pipeline=self.name,
            question=question,
            answer_short="",
            answer_long="",
            answer_type=AnswerType.NOT_FOUND,
            citations=[],
            evidence=[],
            trace=tr.steps,
            usage=tr.usage(self._elapsed_ms(start)),
            status=Status.ERROR,
        )


register(RAGPipeline())
