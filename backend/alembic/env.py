"""Alembic environment.

The database URL always comes from application settings, never from
``alembic.ini``, so migrations cannot be run against a different database than
the one the services use.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from backend.app.core.config import get_settings
from backend.app.models import *  # noqa: F401,F403

# Importing the models package registers every table on Base.metadata.
from backend.app.models import Base  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

_settings = get_settings()
config.set_main_option("sqlalchemy.url", _settings.database.async_url)


def _include_object(
    obj: object, name: str | None, type_: str, reflected: bool, compare_to: object
) -> bool:
    """Keep TimescaleDB's internal schemas out of autogenerate diffs."""
    return not (
        type_ == "table"
        and getattr(obj, "schema", None)
        in {
            "_timescaledb_internal",
            "_timescaledb_catalog",
            "_timescaledb_config",
            "_timescaledb_cache",
            "timescaledb_information",
            "timescaledb_experimental",
        }
    )


def run_migrations_offline() -> None:
    context.configure(
        url=_settings.database.async_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        include_object=_include_object,
        # SQLite cannot ALTER most things in place; batch mode makes the same
        # migration scripts usable for hermetic tests.
        render_as_batch=connection.dialect.name == "sqlite",
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(_run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
