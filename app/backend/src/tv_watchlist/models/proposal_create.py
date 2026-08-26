"""A proposal body that builds a brand-new category workbook."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, model_validator

from tv_watchlist.models.category_create import CategoryCreate


class ProposalCreate(BaseModel):
    """The create arm of a proposal: one whole new-category request."""

    kind: Literal["create"]
    category: CategoryCreate

    @model_validator(mode="after")
    def _require_researched_rows(self) -> ProposalCreate:
        """`titles` belongs to the hand-typed dialog: a diff built from it would show the user nothing."""
        if not self.category.rows:
            raise ValueError("a create proposal needs rows, since the diff is what the user approves")
        return self
