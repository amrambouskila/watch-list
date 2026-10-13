"""Alembic entrypoint: the one asyncpg URL the app uses, bridged into Alembic's sync API with run_sync."""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from tv_watchlist.config import get_settings
from tv_watchlist.data import models  # noqa: F401 - importing the package registers every table on Base.metadata
from tv_watchlist.data.alembic_support import escaped_url, include_object
from tv_watchlist.data.base import Base

config = context.config
if config.config_file_name is not None:
    # disable_existing_loggers defaults to True, which would mute every logger this ini does not name -
    # including the app's own - the moment a migration runs in-process rather than from the CLI.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# The test harness hands in a URL through set_main_option; otherwise it is the app's own. Never the ini's.
if not config.get_main_option("sqlalchemy.url"):
    config.set_main_option("sqlalchemy.url", escaped_url(get_settings().database_url))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL without a connection (`alembic upgrade head --sql`)."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """The sync half of the bridge: Alembic's migration API, handed a connection run_sync owns."""
    context.configure(
        connection=connection, target_metadata=target_metadata, include_object=include_object, compare_type=True
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """NullPool: a migration run opens one connection and must leave none behind for the app's own engine."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
