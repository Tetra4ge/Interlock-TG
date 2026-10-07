import hashlib
import json
import re
from typing import Any

from pydantic import BaseModel, Field

from server.graph.queries import GraphQueryError, entity_names, run_installed_strict
from server.pipelines.agent.guardrails import check_graph_call, to_gsql_params
from server.pipelines.agent.tools.base import ToolContext, ToolResult, error

CATALOGUE = """\
Run ONE of these named, read-only graph queries for questions neighbors cannot express.
Graph: Person -DIRECTOR_OF-> Company; Company -AUDITED_BY-> AuditFirm; Company -SUBSIDIARY_OF->
Company; Company|Person -PARTY_TO-> RelatedPartyTxn.
Ids look like C:TATASTEEL, P:x1a2b3c, A:x4d5e6f.
Results have no source pages: confirm any fact you will cite with neighbors or search_text.

Queries (params is an object):
- shared_directors {company_ids: [C:..] (1-10), fiscal_year?: "FY2023-24"} -> people on the board of
  ALL the given companies.
- path_between {source_id, target_id, max_hops?: 1-4 (default 3)} -> shortest connecting path.
- stake_aggregate {company_id} -> total pledged stake percentage held through the company.
- entity_neighbors {entity_ids: [..] (1-10), hops?: 1-2, fiscal_year?} -> raw connected ids.

Examples:
 shared_directors  {"company_ids": ["C:TATASTEEL", "C:TATAMOTORS"], "fiscal_year": "FY2023-24"}
 path_between      {"source_id": "P:x1a2b3c", "target_id": "C:BAJFINANCE", "max_hops": 3}
 stake_aggregate   {"company_id": "C:TATAMOTORS"}
Max 200 rows are returned; at most 60 are shown."""

DESCRIPTION = CATALOGUE

_ENTITY_IN_TEXT = re.compile(r"\b[CPA]:[A-Za-z0-9_\-]{1,62}")


class GraphQueryArgs(BaseModel):
    query_name: str = Field(max_length=64)
    params: dict[str, Any] = Field(default_factory=dict)
    purpose: str = Field(default="", max_length=200)


def _row(key: str, value: Any) -> str:
    if isinstance(value, dict) and "v_id" in value:
        attrs = value.get("attributes") or {}
        label = attrs.get("name") or ""
        return f"{key}: {value['v_id']} [{value.get('v_type', '')}] {label}".rstrip()
    return f"{key}: {json.dumps(value, default=str)}"


def flatten_rows(raw: Any) -> list[str]:
    """runInstalledQuery output -> one compact line per printed row."""
    rows: list[str] = []
    for block in raw if isinstance(raw, list) else []:
        if not isinstance(block, dict):
            rows.append(json.dumps(block, default=str))
            continue
        for key, value in block.items():
            if isinstance(value, list):
                rows.extend(_row(key, v) for v in value)
            else:
                rows.append(f"{key}: {json.dumps(value, default=str)}")
    return rows


def run(ctx: ToolContext, args: GraphQueryArgs) -> ToolResult:
    ok, reason, validated = check_graph_call(args.query_name, args.params)
    if not ok:
        return error(f"query rejected: {reason}")
    try:
        gsql_params = to_gsql_params(args.query_name, validated)
    except ValueError as e:
        return error(f"query rejected: {e}. Ids must come from find_entity (C:, P: or A: prefix)")

    try:
        raw = run_installed_strict(args.query_name, gsql_params, ctx.cfg.gsql_timeout_seconds)
    except GraphQueryError as e:
        return error(f"query failed: {str(e)[:300]}")

    rows = flatten_rows(raw)[: ctx.cfg.gsql_max_rows]
    total = len(rows)
    if total == 0:
        return ToolResult(ok=True, text=f"{args.query_name} returned no rows for these parameters.")

    shown = rows[: ctx.cfg.shown_rows]
    body = "\n".join(shown)
    if total > len(shown):
        body += f"\n... {total - len(shown)} more rows truncated"
    names = entity_names(sorted(set(_ENTITY_IN_TEXT.findall(body))))
    if names:
        body += "\nnames: " + "; ".join(f"{i} = {n}" for i, (n, _) in sorted(names.items()))

    digest = hashlib.sha256(
        json.dumps([args.query_name, validated], sort_keys=True).encode()
    ).hexdigest()[:12]
    text = (
        f"{args.query_name}({json.dumps(validated, sort_keys=True)}) [computed by query]:\n{body}"
    )
    label = ctx.log.add("tool_result", f"query:{digest}", text)
    return ToolResult(ok=True, text=f"[{label}] {text}", labels=[label])
