"""A read-only companion sheet (media inventory, scope and sources, notes)."""

from __future__ import annotations

from pydantic import BaseModel


class ReferenceSheet(BaseModel):
    """Non-editable supporting sheet shown in the info drawer."""

    title: str
    header: list[str]
    rows: list[list[str]]
