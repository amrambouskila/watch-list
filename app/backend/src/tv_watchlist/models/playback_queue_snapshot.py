from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from tv_watchlist.models.playback_occurrence import PlaybackOccurrence


class PlaybackQueueSnapshot(BaseModel):
    """Semantic queue digest and every live occurrence of the completed subjects."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    occurrences: tuple[PlaybackOccurrence, ...]
