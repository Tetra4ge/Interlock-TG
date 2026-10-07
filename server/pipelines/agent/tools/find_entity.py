from typing import Literal

from pydantic import BaseModel, Field

from server.pipelines.agent.tools.base import ToolContext, ToolResult, error
from server.pipelines.graphrag.linking import find_candidates

DESCRIPTION = (
    "Find companies, people or audit firms by name. Use this first to get entity_id "
    "values. Returns up to 5 candidates with match scores (100 = exact)."
)


class FindEntityArgs(BaseModel):
    name: str = Field(min_length=1, max_length=200, description="Name as written in the question")
    kind: Literal["company", "person", "audit_firm", "any"] = "any"


def run(ctx: ToolContext, args: FindEntityArgs) -> ToolResult:
    candidates = find_candidates(args.name, None if args.kind == "any" else args.kind, limit=5)
    if not candidates:
        return error(f"no entity matches {args.name!r}; try a shorter or alternative spelling")
    lines = [
        f"{i}. {c['entity_id']} - {c['canonical_name']} ({c['kind']}), match {c['match']}"
        for i, c in enumerate(candidates, start=1)
    ]
    return ToolResult(ok=True, text="Candidates (lookups, not evidence):\n" + "\n".join(lines))
