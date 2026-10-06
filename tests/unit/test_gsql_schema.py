import re
from pathlib import Path

SCHEMA = Path("server/graph/gsql/schema.gsql").read_text()

# Edges that traversals walk backwards must declare a reverse edge (TRD 6.2),
# otherwise an undirected pattern from the TO side reaches nothing.
EXPECTED_REVERSE = {
    "IN_SECTOR": "SECTOR_OF",
    "DIRECTOR_OF": "HAS_DIRECTOR",
    "PARTY_TO": "HAS_PARTY",
    "HOLDS_STAKE": "HELD_BY",
    "SUBSIDIARY_OF": "HAS_SUBSIDIARY",
    "AUDITED_BY": "AUDITS",
    "NAMED_IN": "NAMES",
    "HAS_CHUNK": "CHUNK_OF",
    "MENTIONS": "MENTIONED_IN",
}


def test_every_directed_edge_declares_its_reverse_edge() -> None:
    for line in SCHEMA.splitlines():
        m = re.match(r"CREATE DIRECTED EDGE (\w+)", line)
        if not m:
            continue
        name = m.group(1)
        assert name in EXPECTED_REVERSE, f"unexpected edge {name}"
        assert f'REVERSE_EDGE="{EXPECTED_REVERSE[name]}"' in line, name
