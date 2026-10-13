"""The one place a stored numbering is resolved into an episode (R70).

`episode_order.sequence` is a dense 1-based rank inside ONE numbering, so "the 62nd episode of One Piece's
absolute ordering" is a row to read, never a sum to compute. TMDB numbers anime absolute-continuously
inside season buckets - season 2 runs 62-77 - so arithmetic over `episode.(season_number, episode_number)`
is right for Western TV and silently wrong for anime (CLAUDE.md section 11.2, rule 9). This module exists so
that no caller ever writes that arithmetic, and so that the two callers that resolve a numbering - the
episode join beside it, and Phase 3.5's identify pass - address `episode_order` exactly one way.

**There is no fallback.** A numbering a title does not carry answers `None`, and a slot past the end of one
answers `None`. Falling back to the aired rank would produce a confidently wrong episode, which is the one
failure shape that looks right on screen (`ingest/expansion.py` refuses it for the same reason).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import ColumnElement, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from tv_watchlist.data.models import Episode, EpisodeOrder
from tv_watchlist.ingest.episode_orders import NO_LABEL


def within_numberings(numberings: Sequence[tuple[str, str]]) -> ColumnElement[bool]:
    """The `episode_order` predicate for one or more `(order_type, label)` numberings, spelled once.

    The label is half the key, not decoration: the specials bucket is written under `alternate` with
    `SPECIALS_ORDER_LABEL`, and a provider ordering of the same type sits beside it under the empty one.
    """
    return or_(
        *(and_(EpisodeOrder.order_type == order_type, EpisodeOrder.label == label) for order_type, label in numberings)
    )


async def episode_for_sequence(
    session: AsyncSession, title_id: uuid.UUID, order_type: str, label: str = NO_LABEL, *, sequence: int
) -> Episode | None:
    """The episode at `(title_id, order_type, label, sequence)`, or `None` when that slot does not exist.

    One indexed lookup on `uq(title_id, order_type, label, sequence)`. `sequence` is keyword-only so the
    label can carry its default and still sit where the numbering's own key puts it.
    """
    statement = (
        select(Episode)
        .join(EpisodeOrder, EpisodeOrder.episode_id == Episode.id)
        .where(
            EpisodeOrder.title_id == title_id,
            within_numberings(((order_type, label),)),
            EpisodeOrder.sequence == sequence,
        )
    )
    return await session.scalar(statement)
