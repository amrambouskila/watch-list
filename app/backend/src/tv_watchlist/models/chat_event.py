"""One frame of the chat stream, serialised once per SSE data line."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from tv_watchlist.models.proposal import Proposal

ChatEventType = Literal["text", "tool", "proposal", "error", "done"]


class ChatEvent(BaseModel):
    """A single streamed frame; only the fields its type uses are populated."""

    type: ChatEventType
    text: str | None = None
    name: str | None = None
    detail: str | None = None
    state: str | None = None
    proposal: Proposal | None = None
    code: str | None = None
    message: str | None = None
    turns: int | None = None
    total_cost_usd: float | None = None
