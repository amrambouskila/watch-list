"""One image a provider offers for a work, in the shape the `artwork` table stores.

This is deliberately the ingest's own vocabulary rather than a `models/tmdb/` payload. T13's client has
no `/images` endpoint, so the only artwork TMDB hands this app today is the `poster_path` and
`backdrop_path` on a details document, which carry no width, language or vote. When an images call is
added, its payload is converted into this shape at the same boundary every other TMDB field crosses.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from tv_watchlist.data.enums import ArtworkKind


@dataclass(frozen=True, slots=True)
class ArtworkCandidate:
    """`remote_path` is the provider's own path, and it is never used as a filename (CLAUDE.md B11)."""

    kind: ArtworkKind
    remote_path: str
    language: str | None = None
    vote_average: Decimal | None = None
    width: int | None = None
    height: int | None = None
    aspect_ratio: Decimal | None = None
