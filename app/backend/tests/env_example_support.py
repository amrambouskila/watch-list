"""The root .env.example, parsed the way the two consumers (pydantic-settings, docker compose) read it."""

from __future__ import annotations

from pathlib import Path
from typing import Final

from tv_watchlist.config import Settings

ENV_EXAMPLE_PATH: Final[Path] = Path(__file__).resolve().parents[3] / ".env.example"


def env_example_lines() -> list[str]:
    return ENV_EXAMPLE_PATH.read_text(encoding="utf-8").splitlines()


def env_example_entries() -> dict[str, str]:
    """`NAME -> placeholder`, in file order; comment and blank lines skipped."""
    entries: dict[str, str] = {}
    for line in env_example_lines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        name, _, value = stripped.partition("=")
        entries[name.strip()] = value.strip()
    return entries


def settings_env_names() -> frozenset[str]:
    """Every `TV_...` name `Settings` will actually read.

    The prefix is read off `Settings.model_config` rather than hard-coded again, so this stays correct
    if `config.py`'s `env_prefix` ever changes without anyone remembering to update a second copy of it.
    """
    prefix = Settings.model_config.get("env_prefix", "")
    return frozenset(f"{prefix}{name.upper()}" for name in Settings.model_fields)
