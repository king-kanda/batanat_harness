"""Shared fixtures.

Database tests run against a real Postgres — the schema relies on partial
unique indexes, native enums and JSONB, none of which SQLite can honour, and a
dedupe guarantee tested against a different engine is not tested at all.

The suite creates and drops its own database (`<db>_test`) so it can never
touch development data. If Postgres is unreachable, those tests skip rather
than fail: the rest of the suite still has to pass on a laptop with nothing
running.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from urllib.parse import urlsplit, urlunsplit

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from batanat_api.config import get_settings
from batanat_api.core.db_bootstrap import split_dsn
from batanat_api.db.base import Base
from batanat_api.db.models import User
from batanat_api.db.session import to_async_dsn

TEST_DB_SUFFIX = "_test"


def _test_dsn() -> str:
    """The DSN of the throwaway test database.

    Rewrite only the path component. A string replace of "/postgres" also
    matches the username in "//postgres:password@…", which silently produces a
    DSN for a user that does not exist.
    """
    parts = urlsplit(get_settings().database_url)
    _, database = split_dsn(get_settings().database_url)
    return urlunsplit(
        (parts.scheme, parts.netloc, f"/{database}{TEST_DB_SUFFIX}", parts.query, parts.fragment)
    )


async def _postgres_available() -> bool:
    import asyncpg

    maintenance, _ = split_dsn(get_settings().database_url)
    try:
        conn = await asyncio.wait_for(asyncpg.connect(maintenance), timeout=3)
    except Exception:
        return False
    await conn.close()
    return True


@pytest.fixture(scope="session")
def postgres_available() -> bool:
    return asyncio.run(_postgres_available())


@pytest.fixture(autouse=True)
def _encryption_key(monkeypatch: pytest.MonkeyPatch) -> str:
    """Every test gets a real, ephemeral master key. Never the developer's."""
    key = Fernet.generate_key().decode()
    settings = get_settings()
    monkeypatch.setattr(settings, "token_encryption_key", key, raising=False)
    return key


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def _clean_redis_keys():
    """Clear this project's Redis keys between tests.

    Rate-limit counters and OAuth states live in Redis, which survives the test
    process — without this, a rate-limit test poisons the next *run*, not just
    the next test. Only our own prefixes are deleted: this Redis instance is
    shared with other projects on the dev machine, so FLUSHDB is not an option.
    """
    from redis.asyncio import from_url

    client = from_url(get_settings().redis_url)
    try:
        for prefix in ("pairing:*", "oauth:state:*"):
            keys = [key async for key in client.scan_iter(match=prefix)]
            if keys:
                await client.delete(*keys)
    except Exception:  # noqa: BLE001 — Redis absent is not a test failure here
        pass
    finally:
        await client.aclose()
    yield


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def db_engine(postgres_available: bool):
    """Create the test database once for the whole session, drop it at the end.

    Creating a database per test cost five minutes of wall clock; per session it
    costs a few seconds. Isolation comes from the transaction in `session`
    below, not from rebuilding the schema each time.
    """
    if not postgres_available:
        pytest.skip("Postgres is not reachable; skipping database tests.")

    import asyncpg

    maintenance, database = split_dsn(get_settings().database_url)
    test_database = f"{database}{TEST_DB_SUFFIX}"

    admin = await asyncpg.connect(maintenance)
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{test_database}" WITH (FORCE)')
        await admin.execute(f'CREATE DATABASE "{test_database}"')
    finally:
        await admin.close()

    engine = create_async_engine(to_async_dsn(_test_dsn()))
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    await engine.dispose()
    admin = await asyncpg.connect(maintenance)
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{test_database}" WITH (FORCE)')
    finally:
        await admin.close()


@pytest_asyncio.fixture(loop_scope="session")
async def session(db_engine) -> AsyncIterator[AsyncSession]:
    """A session inside a transaction that is always rolled back.

    Tests call `commit()` freely — with `create_savepoint` that releases a
    savepoint rather than the outer transaction, so constraint violations still
    surface exactly as they would in production, and the database is pristine
    for the next test.
    """
    async with db_engine.connect() as connection:
        transaction = await connection.begin()
        factory = async_sessionmaker(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        async with factory() as session:
            yield session
        await transaction.rollback()


@pytest_asyncio.fixture(loop_scope="session")
async def user(session: AsyncSession) -> User:
    user = User(email=f"demo-{uuid.uuid4().hex[:8]}@batanat.test", name="Demo")
    session.add(user)
    await session.commit()
    return user
