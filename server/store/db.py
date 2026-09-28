from pathlib import Path
from typing import Any

import libsql

from server.settings import settings

MIGRATIONS = Path(__file__).parent / "migrations"


def connect() -> Any:
    """
    Connect to Turso DB or local libSQL DB using the libsql SDK (sqlite3-like sync API).
    """
    url = settings.turso_database_url
    if url.startswith("file:"):
        path = url.removeprefix("file:")
        Path(path).parent.mkdir(parents=True, exist_ok=True)

    return libsql.connect(database=url, auth_token=settings.turso_auth_token)


def _strip_line_comments(sql: str) -> str:
    """Drop '-- ...' line comments before splitting on ';', so a semicolon
    inside a comment can't be mistaken for a statement terminator."""
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())


def migrate() -> None:
    """
    Run migrations from store/migrations/*.sql
    """
    conn = connect()
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)")
    applied = {r[0] for r in conn.execute("SELECT version FROM schema_version").fetchall()}

    for f in sorted(MIGRATIONS.glob("*.sql")):
        v = int(f.name.split("_")[0])
        if v not in applied:
            for stmt in _strip_line_comments(f.read_text()).split(";"):
                stmt = stmt.strip()
                if stmt:
                    conn.execute(stmt)
            conn.execute("INSERT INTO schema_version(version) VALUES (?)", [v])
            conn.commit()
    conn.close()
