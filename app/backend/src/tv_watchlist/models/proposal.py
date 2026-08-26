"""A validated change Claude offers, held for your approval before anything is written."""

from __future__ import annotations

from pydantic import BaseModel, Field

from tv_watchlist.constants import MAX_PROPOSAL_SOURCES
from tv_watchlist.models.proposal_create import ProposalCreate
from tv_watchlist.models.proposal_edit import ProposalEdit
from tv_watchlist.models.proposal_hero import ProposalHero


class Proposal(BaseModel):
    """One pending proposal: what it does, where it came from, and the body to apply."""

    id: str
    summary: str
    sources: list[str] = Field(default_factory=list, max_length=MAX_PROPOSAL_SOURCES)
    body: ProposalCreate | ProposalEdit | ProposalHero = Field(discriminator="kind")
