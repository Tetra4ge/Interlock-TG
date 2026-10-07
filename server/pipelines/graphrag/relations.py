import re

from pydantic import BaseModel

from server.pipelines.common.tracer import Tracer
from server.pipelines.graphrag.linking import RELATION_TYPES, LinkPlan

KEYWORD_RULES: dict[str, re.Pattern[str]] = {
    "DIRECTOR_OF": re.compile(
        r"\b(directors?|directorships?|board|independent|appointed|resign\w*)\b", re.IGNORECASE
    ),
    "AUDITED_BY": re.compile(r"\b(auditors?|audited|audit firms?)\b", re.IGNORECASE),
    "PARTY_TO": re.compile(
        r"\b(related[- ]part(?:y|ies)|transactions?|loans?|sale to|purchase from)\b", re.IGNORECASE
    ),
    "HOLDS_STAKE": re.compile(
        r"\b(stakes?|shareholdings?|shareholders?|promoters?|pledg\w*)\b", re.IGNORECASE
    ),
    "SUBSIDIARY_OF": re.compile(r"\b(subsidiar\w*|group compan\w*)\b", re.IGNORECASE),
    "NAMED_IN": re.compile(r"\b(orders?|penalt\w*|regulators?|debarred)\b", re.IGNORECASE),
    "IN_SECTOR": re.compile(r"\b(sectors?|industry|industries)\b", re.IGNORECASE),
}

# High-degree relation types: expanding through them at hop 2 floods the context
# with unrelated triples, so they are only followed when the question asks for them.
HUB_RELATIONS = frozenset({"IN_SECTOR", "AUDITED_BY"})


class RelationChoice(BaseModel):
    types: list[str]  # what hop 1 expands
    explicit: list[str]  # what the question (or helper model) actually asked for

    @property
    def hop2_types(self) -> list[str]:
        explicit = set(self.explicit)
        return [t for t in self.types if t not in HUB_RELATIONS or t in explicit]


def keyword_relations(question: str) -> list[str]:
    return [rel for rel, pattern in KEYWORD_RULES.items() if pattern.search(question)]


def choose_relations(question: str, plan: LinkPlan, tracer: Tracer | None = None) -> RelationChoice:
    """Union of the helper model's relation types and keyword rules (robust when
    the helper call is weak). Empty means "no idea", so all types are expanded."""
    wanted = set(plan.relation_types) | set(keyword_relations(question))
    explicit = [r for r in RELATION_TYPES if r in wanted]
    choice = RelationChoice(types=explicit or list(RELATION_TYPES), explicit=explicit)
    if tracer is not None:
        tracer.add(
            "retrieve",
            "choose_relations",
            f"llm={plan.relation_types or '[]'}",
            ", ".join(choice.types) + ("" if explicit else " (all: nothing specific found)"),
        )
    return choice
