"""Alembic environment.

The database URL comes from the application settings, not from alembic.ini —
there is one source of truth for where the database lives, and it is `.env`.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from batanat_api.config import get_settings

# Importing the models registers every table on Base.metadata. Without this,
# autogenerate would cheerfully produce a migration that drops the schema.
from batanat_api.db import models  # noqa: F401
from batanat_api.db.base import Base
from batanat_api.db.session import to_async_dsn

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", to_async_dsn(get_settings().database_url))

target_metadata = Base.metadata

#: Tables created and owned by libraries, not by our models. Autogenerate sees
#: them in the database, does not see them in `Base.metadata`, and concludes
#: they should be dropped — which silently destroyed LangGraph's checkpoints
#: once already. Anything here is invisible to autogenerate.
FOREIGN_TABLE_PREFIXES = ("checkpoint",)


def include_object(object_, name, type_, reflected, compare_to):
    if type_ == "table" and name and name.startswith(FOREIGN_TABLE_PREFIXES):
        return False
    if type_ == "index" and name and name.startswith(FOREIGN_TABLE_PREFIXES):
        return False
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
