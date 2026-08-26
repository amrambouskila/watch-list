"""A file in the library that could not be parsed as a category."""

from __future__ import annotations

from pydantic import BaseModel


class UnreadableWorkbook(BaseModel):
    """Surfaced so a dropped-in file that fails to open is visible, not silently missing."""

    file_name: str
    reason: str
