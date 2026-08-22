"""Create the application database at startup if it does not exist.

We run against a Postgres instance shared with other projects on this machine,
so the database is provisioned at runtime rather than by the server's own
init scripts. This only creates the *database* — tables are Alembic's job in
phase 1.

Creating a database is not transactional and `CREATE DATABASE IF NOT EXISTS`
does not exist in Postgres, so we check the catalogue first and tolerate the
race where a concurrent process wins.
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

from batanat_api.core.logging import get_logger

log = get_logger(__name__)

# Connected to when the target database may not exist yet. Always present.
MAINTENANCE_DB = "postgres"


def split_dsn(dsn: str) -> tuple[str, str]:
    """Return `(maintenance_dsn, database_name)` for a Postgres DSN.

    >>> split_dsn("postgresql://u:p@host:5432/batanat")
    ('postgresql://u:p@host:5432/postgres', 'batanat')
    """
    parts = urlsplit(dsn)
    database = parts.path.lstrip("/")
    if not database:
        raise ValueError(f"DATABASE_URL has no database name: {parts.scheme}://…")
    maintenance = urlunsplit(
        (parts.scheme, parts.netloc, f"/{MAINTENANCE_DB}", parts.query, parts.fragment)
    )
    return maintenance, database


async def ensure_database(dsn: str) -> bool:
    """Ensure the database in `dsn` exists. Returns True if it was created."""
    import asyncpg

    maintenance_dsn, database = split_dsn(dsn)

    conn = await asyncpg.connect(maintenance_dsn)
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", database)
        if exists:
            log.debug("db.bootstrap.present", database=database)
            return False

        # Identifiers cannot be parameterised; quote defensively.
        await conn.execute(f'CREATE DATABASE "{database}"')
        log.info("db.bootstrap.created", database=database)
        return True
    except asyncpg.DuplicateDatabaseError:
        # Another worker created it between our check and our CREATE.
        log.debug("db.bootstrap.race", database=database)
        return False
    finally:
        await conn.close()
