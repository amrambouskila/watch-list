"""A proposal body that offers artwork for a category card."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from tv_watchlist.constants import MAX_HERO_CANDIDATES
from tv_watchlist.models.hero_candidate import HeroCandidate


class ProposalHero(BaseModel):
    """The hero arm of a proposal: one category and the images offered for its card."""

    kind: Literal["hero"]
    category_id: str
    # Artwork is a taste call, so the user picks one by eye rather than approving a diff.
    candidates: list[HeroCandidate] = Field(min_length=1, max_length=MAX_HERO_CANDIDATES)
