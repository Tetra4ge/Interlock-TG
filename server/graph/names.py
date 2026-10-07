"""Logical type names and their TigerGraph names.

TigerGraph vertex and edge types are global to a workspace, so they are shared by every graph
in it. The workspace already holds types with the same names (from an older Interlock graph and
an unrelated fraud sample) whose attributes differ from ours. Every type we own therefore gets
the PREFIX in TigerGraph. The Python code keeps the logical names: `client.get_tg_connection`
maps names on the way in and out, and `schema.py` rewrites the GSQL text.
"""

import re
from functools import lru_cache
from pathlib import Path

PREFIX = "IL_"
SCHEMA_FILE = Path(__file__).parent / "gsql" / "schema.gsql"


@lru_cache(maxsize=1)
def type_names() -> frozenset[str]:
    """Every vertex and edge type the schema declares, including reverse edges."""
    text = SCHEMA_FILE.read_text()
    names = set(re.findall(r"CREATE (?:DIRECTED |UNDIRECTED )?(?:VERTEX|EDGE) (\w+)", text))
    names |= set(re.findall(r'REVERSE_EDGE="(\w+)"', text))
    return frozenset(names)


@lru_cache(maxsize=1)
def reverse_to_forward() -> dict[str, str]:
    """Maps each reverse edge name to its forward (declared) name.

    Traversing a directed edge backward returns it under its reverse name (TigerGraph stores the
    reverse edge as a distinct type). Every query result is mapped through this so Python code
    only ever sees the forward name it was written against, regardless of which direction found
    the edge.
    """
    text = SCHEMA_FILE.read_text()
    pairs = re.findall(r'CREATE (?:DIRECTED|UNDIRECTED) EDGE (\w+).*?REVERSE_EDGE="(\w+)"', text)
    return {rev: fwd for fwd, rev in pairs}


def to_tg(name: str) -> str:
    return PREFIX + name if name in type_names() else name


def to_logical(name: str) -> str:
    stripped = name[len(PREFIX) :] if name.startswith(PREFIX) else name
    if stripped not in type_names():
        return name
    return reverse_to_forward().get(stripped, stripped)


def rewrite_gsql(text: str, graphname: str) -> str:
    """Prefix our type names in GSQL text and point it at the configured graph."""
    names = sorted(type_names(), key=len, reverse=True)
    pattern = re.compile(r"\b(" + "|".join(names) + r")\b")
    out = pattern.sub(lambda m: PREFIX + m.group(1), text)
    return re.sub(r"\bGRAPH Interlock\b", f"GRAPH {graphname}", out)


def map_back(value: object) -> object:
    """Recursively replace prefixed type names in a TigerGraph response with logical names."""
    if isinstance(value, str):
        return to_logical(value)
    if isinstance(value, list):
        return [map_back(v) for v in value]
    if isinstance(value, dict):
        return {k: map_back(v) for k, v in value.items()}
    return value


def map_forward(value: object) -> object:
    """Map logical type names in query parameters to their TigerGraph names.

    Recurses into dicts too: `runInstalledQuery` is called with a params dict whose values
    (not just top-level lists) hold the type-name strings that need mapping, e.g.
    {"seed_ids": [...], "edge_types": ["DIRECTOR_OF", ...]}.
    """
    if isinstance(value, str):
        return to_tg(value)
    if isinstance(value, list):
        return [map_forward(v) for v in value]
    if isinstance(value, dict):
        return {k: map_forward(v) for k, v in value.items()}
    return value
