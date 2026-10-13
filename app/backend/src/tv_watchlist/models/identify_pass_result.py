"""Identification counters, separate from discovery's scan result."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class IdentifyPassResult(BaseModel):
    """Only rows processed by this identification pass contribute to these counts."""

    model_config = ConfigDict(frozen=True)

    identified: int = Field(default=0, ge=0)
    unidentified: int = Field(default=0, ge=0)
