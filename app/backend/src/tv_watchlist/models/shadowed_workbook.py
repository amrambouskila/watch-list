"""A file in the library the app cannot reach, because another file answers to the id its name derives."""

from __future__ import annotations

from pydantic import BaseModel


class ShadowedWorkbook(BaseModel):
    """Surfaced so a dropped-in namesake is visible, rather than silently hiding the file it shadows."""

    file_name: str
    category_id: str
    answered_by: str
