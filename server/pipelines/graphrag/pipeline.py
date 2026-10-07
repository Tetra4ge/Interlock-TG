import time

from server.graph.queries import entity_names
from server.llm.gateway import SpendCapExceeded
from server.pipelines.base import register
from server.pipelines.common.answer import final_answer
from server.pipelines.common.budget import fit_to_budget, split_budget
from server.pipelines.common.evidence import chunk_evidence
from server.pipelines.common.render import assign_labels
from server.pipelines.common.result import build_result, error_result
from server.pipelines.common.tracer import Tracer
from server.pipelines.config import GRAPHRAG, RETRIEVAL
from server.pipelines.graphrag.expand import ExpansionFailed, expand, seed_ids
from server.pipelines.graphrag.global_mode import global_evidence
from server.pipelines.graphrag.linked_text import entity_ids_for_text, linked_text
from server.pipelines.graphrag.linking import LinkPlan, link_entities, plan_question, usable
from server.pipelines.graphrag.models import Triple
from server.pipelines.graphrag.rank import rank_and_cap
from server.pipelines.graphrag.relations import choose_relations
from server.pipelines.graphrag.serialize import serialize
from server.pipelines.models import AnswerResult, EvidenceItem
from server.pipelines.rag import _excluded_doc_ids, retrieve_chunks

Evidence = tuple[list[EvidenceItem], dict[str, dict]]


class GraphRAGPipeline:
    """Single pass: link entities, expand a bounded subgraph, attach linked text,
    answer once. Everything it retrieves is decided before it sees any result,
    which is the limitation Phase 7's agent exists to remove."""

    name = "graphrag"

    def answer(self, question: str, request_id: str) -> AnswerResult:
        tr = Tracer(request_id, self.name)
        start = time.perf_counter()
        try:
            plan = plan_question(question, tr)
            evidence = self._graph_evidence(question, plan, tr)
            if evidence is None:
                evidence = self._vector_evidence(question, tr)

            items, provenance = evidence
            labels = assign_labels(items, provenance)
            model_answer, err = final_answer(tr, question, labels)
            if model_answer is None:
                return error_result(self.name, question, tr, err or "unknown_error", start)
            return build_result(self.name, question, tr, model_answer, labels, start)
        except Exception as e:
            reason = "spend_cap" if isinstance(e, SpendCapExceeded) else repr(e)
            return error_result(self.name, question, tr, reason, start)

    def _graph_evidence(self, question: str, plan: LinkPlan, tr: Tracer) -> Evidence | None:
        """Triples plus linked text, split within the shared budget. None means
        "use vector evidence instead" and the reason is already in the trace."""
        if plan.is_global and GRAPHRAG.global_enabled:
            stats = global_evidence(question, plan, tr)
            if stats is not None:
                return stats
            self._note_fallback(tr, "no_global_statistics")
            return None

        linked = usable(link_entities(plan.mentions, tr))
        if not linked:
            self._note_fallback(tr, "no_entity_linked")
            return None

        relations = choose_relations(question, plan, tr)
        try:
            triples = expand(seed_ids(linked), relations, plan.fiscal_years, tr)
        except ExpansionFailed as e:
            self._note_fallback(tr, "expansion_failed", str(e))
            return None
        if not triples:
            self._note_fallback(tr, "empty_subgraph")
            return None

        linked_ids = [le.entity_id for le in linked]
        names = self._names(triples, linked_ids)
        ranked = rank_and_cap(
            triples, set(seed_ids(linked)), set(relations.explicit), plan.fiscal_years,
            question, names, GRAPHRAG,
        )  # fmt: skip
        triple_items, triple_prov = serialize(ranked, names)

        chunks = linked_text(
            question,
            entity_ids_for_text(linked_ids, ranked),
            plan.fiscal_years,
            _excluded_doc_ids(),
            tr,
            GRAPHRAG,
        )
        chunk_items, chunk_prov = chunk_evidence(chunks)

        items, split = split_budget(
            triple_items, chunk_items, RETRIEVAL.evidence_token_budget, GRAPHRAG.triple_budget_share
        )
        kept_triples = sum(i.kind == "triple" for i in items)
        tr.add(
            "retrieve",
            "budget_split",
            f"budget={split.total} triple_share={GRAPHRAG.triple_budget_share}",
            f"triples {kept_triples}/{len(triple_items)} ({split.primary_tokens} tok), "
            f"chunks {len(items) - kept_triples}/{len(chunk_items)} ({split.secondary_tokens} tok)",
        )
        return items, {**triple_prov, **chunk_prov}

    @staticmethod
    def _names(triples: list[Triple], linked_ids: list[str]) -> dict[str, tuple[str, str]]:
        ids = set(linked_ids)
        for t in triples:
            ids.update(i for i in t.endpoints() if i.startswith(("C:", "P:", "A:")))
        return entity_names(sorted(ids))

    @staticmethod
    def _note_fallback(tr: Tracer, reason: str, detail: str = "") -> None:
        tr.add("retrieve", "fallback", reason, "fallback=vector", error=detail or None)
        return None

    @staticmethod
    def _vector_evidence(question: str, tr: Tracer) -> Evidence:
        """Same retrieval RAG uses, so GraphRAG is never worse than RAG just
        because the graph had nothing to say."""
        items, provenance = chunk_evidence(retrieve_chunks(question, tr))
        return fit_to_budget(items, RETRIEVAL.evidence_token_budget), provenance


register(GraphRAGPipeline())
