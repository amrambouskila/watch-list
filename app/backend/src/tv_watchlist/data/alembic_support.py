"""Pure helpers alembic/env.py imports, kept here so they are testable without running a migration."""

from __future__ import annotations

from typing import Final

VIEW_NAMES: Final[frozenset[str]] = frozenset({"episode_watch_state", "curated_entry_watch_state"})


def escaped_url(database_url: str) -> str:
    """alembic.ini is ConfigParser syntax: a `%` in a password must be doubled before set_main_option."""
    return database_url.replace("%", "%%")


def include_object(obj: object, name: str | None, type_: str, reflected: bool, compare_to: object) -> bool:
    """Autogenerate does not know about views, so the two views never appear in a diff as tables to drop."""
    return not (type_ == "table" and name in VIEW_NAMES)
