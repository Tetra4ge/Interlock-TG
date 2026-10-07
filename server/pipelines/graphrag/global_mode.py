import time

from server.graph.stats import StatItem, dataset_stats_pack
from server.pipelines.common.budget import fit_to_budget
from server.pipelines.common.result import elapsed_ms
from server.pipelines.common.tracer import Tracer
from server.pipelines.config import RETRIEVAL
from server.pipelines.graphrag.linking import LinkPlan
from server.pipelines.graphrag.relations import keyword_relations
from server.pipelines.models import EvidenceItem

# A statistics item is not a document page, so its citations resolve to no doc.
STATS_SECTION = "dataset_stats"
COVERAGE_TOPIC = "COVERAGE"


def rank_stats(pack: list[StatItem], wanted: set[str]) -> list[StatItem]:
    """Coverage first (so the model knows the figures' scope), then statistics
    about the requested relations, then the rest. Order within a group is stable."""

    def group(item: StatItem) -> int:
        if item.topic == COVERAGE_TOPIC:
            return 0
        return 1 if item.topic in wanted else 2

    return sorted(pack, key=group)


def global_evidence(
    question: str, plan: LinkPlan, tracer: Tracer
) -> tuple[list[EvidenceItem], dict[str, dict]] | None:
    """Evidence for questions about the whole dataset: precomputed statistics,
    not an LLM-chosen aggregation query (which would make this agentic). None
    means there is nothing to offer and the caller should fall back."""
    t0 = time.perf_counter()
    pack = dataset_stats_pack()
    if not pack:
        tracer.add("retrieve", "global_stats", question, "no statistics available")
        return None

    wanted = set(plan.relation_types) | set(keyword_relations(question))
    ranked = rank_stats(pack, wanted)
    items = [
        EvidenceItem(kind="summary", ref_id=f"stats:{i}", text=s.text) for i, s in enumerate(ranked)
    ]
    kept = fit_to_budget(items, RETRIEVAL.evidence_token_budget)
    provenance = {
        i.ref_id: {"doc_id": "", "page_start": 0, "page_end": 0, "section": STATS_SECTION}
        for i in kept
    }
    tracer.add(
        "retrieve",
        "global_stats",
        f"wanted={sorted(wanted) or 'any'}",
        f"{len(kept)}/{len(items)} statistics",
        latency_ms=elapsed_ms(t0),
    )
    return kept, provenance
