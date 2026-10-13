"""The discovery pass's counts, before identification or any media write."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ImportScanResult(BaseModel):
    """Unique regular files inspected, their outcomes, and observable boundary refusals."""

    model_config = ConfigDict(frozen=True)

    staging_dir: str
    candidates_seen: int = Field(ge=0)
    found: int = Field(ge=0)
    already_known: int = Field(ge=0)
    too_small: int = Field(ge=0)
    wrong_extension: int = Field(ge=0)
    qbittorrent_reachable: bool
    qbittorrent_outside_staging: int = Field(ge=0)
    path_refused: int = Field(ge=0)
    unreadable: int = Field(ge=0)
