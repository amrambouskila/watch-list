"""Runtime settings, all overridable through the environment."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from tv_watchlist.constants import BACKUP_DIRNAME, BACKUP_INTERVAL_SECONDS, BACKUP_RETENTION, HERO_DIRNAME


class Settings(BaseSettings):
    """Environment-driven configuration for the watch-order service."""

    model_config = SettingsConfigDict(env_prefix="TV_", env_file=".env", extra="ignore")

    library_dir: Path = Field(default=Path(__file__).resolve().parents[4])
    backend_port: int = Field(default=8284, ge=1, le=65535)
    frontend_port: int = Field(default=5284, ge=1, le=65535)
    backup_dir: Path = Field(default=Path(__file__).resolve().parents[3] / BACKUP_DIRNAME)
    backup_retention: int = Field(default=BACKUP_RETENTION, ge=1)
    backup_interval_seconds: float = Field(default=BACKUP_INTERVAL_SECONDS, ge=0)
    heroes_dir: Path = Field(default=Path(__file__).resolve().parents[3] / HERO_DIRNAME)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton."""
    return Settings()
