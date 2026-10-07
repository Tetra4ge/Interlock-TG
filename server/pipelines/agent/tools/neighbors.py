from typing import Literal

from pydantic import BaseModel, Field, field_validator

from server.graph.queries import entity_names
from server.pipelines.agent.tools.base import ToolContext, ToolResult, check_entity_id, error
from server.pipelines.config import GRAPHRAG
from server.pipelines.graphrag.expand import ExpansionFailed, expand
from server.pipelines.graphrag.linking import RELATION_TYPES
from server.pipelines.graphrag.models import Triple
from server.pipelines.graphrag.rank import rank_and_cap
from server.pipelines.graphrag.relations import RelationChoice
from server.pipelines.graphrag.serialize import serialize

DESCRIPTION = (
    "List facts connected to an entity: directorships, stakes, subsidiaries, auditors, "
    "related-party transactions, regulatory actions. Prefer this over graph_query. "
    "Returns labeled facts with fiscal year, value and source page. hops=2 also follows "
    "the neighbours' own facts (e.g. a director's other boards)."
)

RelType = Literal[
    "DIRECTOR_OF", "HOLDS_STAKE", "SUBSIDIARY_OF", "AUDITED_BY", "PARTY_TO", "NAMED_IN", "IN_SECTOR"
]


class NeighborsArgs(BaseModel):
    entity_id: str = Field(max_length=64)
    rel_types: list[RelType] = Field(
        default_factory=list, description="Empty means every relation type"
    )
    hops: int = Field(default=1, ge=1, le=2)
    fiscal_year: str | None = Field(default=None, pattern=r"^FY\d{4}-\d{2}$")
    limit: int | None = Field(default=None, ge=1, le=60)

    @field_validator("rel_types", mode="before")
    @classmethod
    def _upper(cls, v: object) -> object:
        return [str(x).upper() for x in v] if isinstance(v, list) else v


def log_triples(
    ctx: ToolContext, triples: list[Triple], seeds: set[str], explicit: set[str], limit: int,
    fiscal_years: list[str],
) -> ToolResult:  # fmt: skip
    """Rank, serialize and log triples as evidence; shared with get_evidence."""
    ids: set[str] = set(seeds)
    for t in triples:
        ids.update(i for i in t.endpoints() if i.startswith(("C:", "P:", "A:")))
    names = entity_names(sorted(ids))
    cfg = GRAPHRAG.model_copy(update={"max_triples": limit})
    ranked = rank_and_cap(triples, seeds, explicit, fiscal_years, ctx.question, names, cfg)
    items, prov = serialize(ranked, names)

    blocks, labels = [], []
    for item in items:
        p = prov[item.ref_id]
        label = ctx.log.add(
            "triple", item.ref_id, item.text, p["doc_id"], p["page_start"], p["page_end"],
            p["section"], p["fiscal_year"],
        )  # fmt: skip
        labels.append(label)
        blocks.append(f"[{label}] {item.text}")
    shown = len(items)
    header = f"{shown} facts" + (f" (of {len(triples)} found)" if len(triples) > shown else "")
    return ToolResult(ok=True, text=header + ":\n" + "\n".join(blocks), labels=labels)


def run(ctx: ToolContext, args: NeighborsArgs) -> ToolResult:
    problem = check_entity_id(args.entity_id)
    if problem:
        return error(problem)

    limit = min(args.limit or ctx.cfg.neighbors_default_limit, ctx.cfg.neighbors_max_limit)
    explicit: list[str] = list(args.rel_types)
    choice = RelationChoice(types=explicit or list(RELATION_TYPES), explicit=explicit)
    fiscal_years = [args.fiscal_year] if args.fiscal_year else []
    cfg = GRAPHRAG.model_copy(update={"max_hops": args.hops, "max_triples": limit})

    try:
        triples = expand([args.entity_id], choice, fiscal_years, ctx.tracer, cfg)
    except ExpansionFailed as e:
        return error(f"the graph could not be queried ({str(e)[:200]}); try search_text instead")
    if not triples:
        scope = f" in {args.fiscal_year}" if args.fiscal_year else ""
        return ToolResult(
            ok=True,
            text=f"no facts found for {args.entity_id}{scope} with relation types "
            f"{explicit or 'any'}. The graph may not cover it; try search_text.",
        )
    return log_triples(ctx, triples, {args.entity_id}, set(explicit), limit, fiscal_years)
