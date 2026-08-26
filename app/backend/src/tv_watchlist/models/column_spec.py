"""Description of one column in a watch-order sheet."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ColumnKind = Literal["text", "choice"]
ColumnRole = Literal["order", "title", "watch", "other"]


class ColumnSpec(BaseModel):
    """A single sheet column, as the UI needs to render and edit it."""

    key: str
    label: str
    index: int = Field(ge=1)
    kind: ColumnKind
    role: ColumnRole
    choices: list[str] = Field(default_factory=list)
    width: float | None = None
