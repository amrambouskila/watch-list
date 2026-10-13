"""The identity hints one single-item release filename actually states."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class FilenameParse(BaseModel):
    """A refused filename has no hints and zero confidence."""

    model_config = ConfigDict(frozen=True)

    series_token: str = ""
    year: int | None = None
    season_number: int | None = Field(default=None, ge=0)
    episode_number: int | None = Field(default=None, ge=0)
    absolute_number: int | None = Field(default=None, gt=0)
    confidence: float = Field(default=0, ge=0, le=1)
