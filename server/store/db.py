from pathlib import Path
from typing import Any

import libsql_client

from server.settings import settings

MIGRATIONS = Path(__file__).parent / "migrations"


def connect() -> Any:
    """
    Connect to Turso DB or local libSQL DB using libsql-client.
    """
    url = settings.turso_database_url
    if url.startswith("file:"):
        path = url.removeprefix("file:")
        Path(path).parent.mkdir(parents=True, exist_ok=True)

    return libsql_client.create_client_sync(url=url, auth_token=settings.turso_auth_token or None)


def migrate() -> None:
    """
    Run migrations from store/migrations/*.sql
    """
    conn = connect()
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)")
    rs = conn.execute("SELECT version FROM schema_version")
    applied = {r[0] for r in rs.rows}

    for f in sorted(MIGRATIONS.glob("*.sql")):
        v = int(f.name.split("_")[0])
        if v not in applied:
            for stmt in f.read_text().split(";"):
                stmt = stmt.strip()
                if stmt:
                    conn.execute(stmt)
            conn.execute("INSERT INTO schema_version(version) VALUES (?)", [v])
    conn.close()
