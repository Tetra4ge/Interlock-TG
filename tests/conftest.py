import sqlite3
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

MIGRATIONS = Path(__file__).resolve().parent.parent / "server/store/migrations"


class MemoryDB:
    """A real SQLite database with the project migrations applied, standing
    in for Turso. `close()` is a no-op so code that opens and closes a
    connection per operation keeps seeing the same data."""

    def __init__(self) -> None:
        # Shared by the API's worker threads, so access is serialised.
        self.raw = sqlite3.connect(":memory:", check_same_thread=False)
        self._lock = threading.RLock()
        for f in sorted(MIGRATIONS.glob("*.sql")):
            self.raw.executescript(f.read_text())

    def execute(self, sql: str, params: list | tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            return self.raw.execute(sql, tuple(params))

    def commit(self) -> None:
        with self._lock:
            self.raw.commit()

    def close(self) -> None:
        pass


@pytest.fixture
def memdb() -> Iterator[MemoryDB]:
    db = MemoryDB()
    yield db
    db.raw.close()


@pytest.fixture
def tracer(memdb: MemoryDB, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """A real Tracer writing to the in-memory DB's `traces` table."""
    from server.pipelines.common import tracer as tracer_mod

    monkeypatch.setattr(tracer_mod, "connect", lambda: memdb)
    return tracer_mod.Tracer("req-test", "graphrag")


def seed_entities(db: MemoryDB, rows: list[tuple[str, str, str, str]]) -> None:
    """rows: (entity_id, kind, canonical_name, aliases_text). Builds the FTS
    table exactly as the `entity-index` build step does."""
    db.execute("DROP TABLE IF EXISTS entities_fts")
    db.execute(
        "CREATE VIRTUAL TABLE entities_fts USING fts5("
        "entity_id UNINDEXED, canonical_name, aliases_text, kind UNINDEXED)"
    )
    for eid, kind, name, aliases in rows:
        db.execute(
            "INSERT INTO entities (entity_id, kind, canonical_name, aliases_text) "
            "VALUES (?, ?, ?, ?)",
            [eid, kind, name, aliases],
        )
        db.execute(
            "INSERT INTO entities_fts (entity_id, canonical_name, aliases_text, kind) "
            "VALUES (?, ?, ?, ?)",
            [eid, name, aliases, kind],
        )
    db.commit()
