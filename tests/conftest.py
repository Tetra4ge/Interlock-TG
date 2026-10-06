import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

MIGRATIONS = Path(__file__).resolve().parent.parent / "server/store/migrations"


class MemoryDB:
    """A real SQLite database with the project migrations applied, standing
    in for Turso. `close()` is a no-op so code that opens and closes a
    connection per operation keeps seeing the same data."""

    def __init__(self) -> None:
        self.raw = sqlite3.connect(":memory:")
        for f in sorted(MIGRATIONS.glob("*.sql")):
            self.raw.executescript(f.read_text())

    def execute(self, sql: str, params: list | tuple = ()) -> sqlite3.Cursor:
        return self.raw.execute(sql, tuple(params))

    def commit(self) -> None:
        self.raw.commit()

    def close(self) -> None:
        pass


@pytest.fixture
def memdb() -> Iterator[MemoryDB]:
    db = MemoryDB()
    yield db
    db.raw.close()
