import re
from collections.abc import Iterator
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from server.graph.queries import vertex_param

# fullmatch, not match with ^...$: "$" also matches before a trailing newline.
ID_RE = re.compile(r"[A-Za-z0-9_:\-|]{1,64}")
MAX_VALUE_CHARS = 64
FISCAL_YEAR_PATTERN = r"^FY\d{4}-\d{2}$"


class _Args(BaseModel):
    # Unknown parameters are rejected rather than ignored, so a model (or injected
    # text) cannot smuggle extra fields past validation.
    model_config = ConfigDict(extra="forbid")


class SharedDirectorsArgs(_Args):
    company_ids: list[str] = Field(min_length=1, max_length=10)
    fiscal_year: str | None = Field(default=None, pattern=FISCAL_YEAR_PATTERN)


class PathBetweenArgs(_Args):
    source_id: str
    target_id: str
    max_hops: int = Field(default=3, ge=1, le=4)


class StakeAggregateArgs(_Args):
    company_id: str


class EntityNeighborsArgs(_Args):
    entity_ids: list[str] = Field(min_length=1, max_length=10)
    hops: int = Field(default=1, ge=1, le=2)
    fiscal_year: str | None = Field(default=None, pattern=FISCAL_YEAR_PATTERN)


# The allow-list. The model chooses a name from here and supplies typed
# parameters; it never writes query text.
QUERY_REGISTRY: dict[str, type[_Args]] = {
    "shared_directors": SharedDirectorsArgs,
    "path_between": PathBetweenArgs,
    "stake_aggregate": StakeAggregateArgs,
    "entity_neighbors": EntityNeighborsArgs,
}


def _iter_string_values(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _iter_string_values(v)
    elif isinstance(value, (list, tuple, set)):
        for v in value:
            yield from _iter_string_values(v)


def check_graph_call(name: object, params: object) -> tuple[bool, str, dict[str, Any]]:
    """Returns (ok, reason, validated params). Parameters are later passed as typed
    values to a pre-installed query, never concatenated into query text."""
    if not isinstance(name, str) or name not in QUERY_REGISTRY:
        return (
            False,
            f"unknown query {str(name)[:60]!r}; choose one of {sorted(QUERY_REGISTRY)}",
            {},
        )
    if not isinstance(params, dict):
        return False, "params must be an object", {}
    try:
        args = QUERY_REGISTRY[name](**params)
    except Exception as e:
        return False, f"invalid parameters: {str(e)[:300]}", {}
    dumped = args.model_dump()
    for v in _iter_string_values(dumped):
        if len(v) > MAX_VALUE_CHARS or not ID_RE.fullmatch(v):
            return False, "parameter value has unexpected characters or length", {}
    return True, "ok", dumped


def to_gsql_params(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Validated arguments -> the installed query's parameters. Untyped VERTEX
    parameters need (id, type) tuples; raises ValueError for an id whose type
    cannot be told from its prefix."""
    if name == "shared_directors":
        return {"companies": args["company_ids"], "fiscal_year": args["fiscal_year"] or ""}
    if name == "path_between":
        return {
            "source": vertex_param(args["source_id"]),
            "target": vertex_param(args["target_id"]),
            "max_hops": args["max_hops"],
        }
    if name == "stake_aggregate":
        return {"company": args["company_id"]}
    if name == "entity_neighbors":
        return {
            "seeds": [vertex_param(i) for i in args["entity_ids"]],
            "hops": args["hops"],
            "fiscal_year": args["fiscal_year"] or "",
        }
    raise ValueError(f"no parameter mapping for {name!r}")
