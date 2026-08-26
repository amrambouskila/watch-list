"""A proposal body that edits rows of an existing category."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from tv_watchlist.constants import MAX_PROPOSAL_CHANGES
from tv_watchlist.models.row_change import RowChange


class ProposalEdit(BaseModel):
    """The edit arm of a proposal: one category id, the grid its rows were read from, and the changes."""

    kind: Literal["edit"]
    category_id: str
    # Row numbers mean nothing except against the grid they were resolved on, so the write is guarded
    # against this stamp. Reading one at approve time instead would always match and guard nothing.
    read_mtime: float
    changes: list[RowChange] = Field(max_length=MAX_PROPOSAL_CHANGES)
