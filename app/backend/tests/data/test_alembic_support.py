"""The Alembic wiring: the ConfigParser escape, the view filter, and the ini/env.py contract."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Final

from alembic import command
from alembic.config import Config
from sqlalchemy import URL, pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from tv_watchlist.data.alembic_support import VIEW_NAMES, escaped_url, include_object

BACKEND_DIR: Final[Path] = Path(__file__).resolve().parents[2]
ALEMBIC_INI: Final[Path] = BACKEND_DIR / "alembic.ini"
# A fabricated credential for a database that does not exist. Both characters are the point: `@` splits
# a URL and `%` is ConfigParser syntax, so the chain has to survive each of them.
AWKWARD_CREDENTIAL: Final[str] = "p@ss%word"
DSN: Final[str] = URL.create(
    drivername="postgresql+asyncpg",
    username="tv",
    password=AWKWARD_CREDENTIAL,
    host="127.0.0.1",
    port=5599,
    database="tv_test",
).render_as_string(hide_password=False)


def _harness_config() -> Config:
    """An alembic Config with the URL injected the way T09's integration fixture will inject it."""
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", escaped_url(DSN))
    return config


def test_a_percent_in_the_password_is_doubled_for_configparser() -> None:
    assert escaped_url("postgresql+asyncpg://tv:p%25ss@db:5432/tv") == "postgresql+asyncpg://tv:p%%25ss@db:5432/tv"


def test_a_url_without_a_percent_is_unchanged() -> None:
    assert escaped_url("postgresql+asyncpg://tv:tv@db:5432/tv") == "postgresql+asyncpg://tv:tv@db:5432/tv"


def test_the_two_views_are_kept_out_of_autogenerate() -> None:
    assert VIEW_NAMES == frozenset({"episode_watch_state", "curated_entry_watch_state"})
    for view in VIEW_NAMES:
        assert include_object(object(), view, "table", True, None) is False
    assert include_object(object(), "watch_event", "table", True, None) is True
    assert include_object(object(), "episode_watch_state", "index", True, None) is True


def test_the_ini_carries_no_url_so_env_py_is_the_only_place_one_is_set() -> None:
    assert Config(str(ALEMBIC_INI)).get_main_option("sqlalchemy.url") is None


async def test_the_engine_env_py_builds_is_a_null_pool_on_the_unescaped_password() -> None:
    """Round trip: URL.create escapes, escaped_url doubles, ConfigParser halves, the URL parser unescapes."""
    config = _harness_config()
    engine = async_engine_from_config(
        config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    try:
        assert type(engine.pool) is pool.NullPool
        assert engine.url.password == AWKWARD_CREDENTIAL
    finally:
        await engine.dispose()


def test_a_migration_run_leaves_the_apps_own_loggers_enabled() -> None:
    """fileConfig's default disables every logger it does not name, which would mute the app mid-migration."""
    logger = logging.getLogger("tv_watchlist.agent.handler_guard")
    handlers, level = list(logging.root.handlers), logging.root.level
    try:
        command.upgrade(_harness_config(), "head", sql=True)
        still_enabled = not logger.disabled
    finally:
        # fileConfig rips out the root handlers pytest installed; put them back so a failure here cannot
        # cascade into the next test.
        logging.root.handlers[:] = handlers
        logging.root.setLevel(level)
        logger.disabled = False
    assert still_enabled
