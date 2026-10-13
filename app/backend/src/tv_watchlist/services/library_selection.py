from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Row

from tv_watchlist.data.enums import JellyfinItemKind

type LibraryRow = Row[tuple[uuid.UUID, uuid.UUID, JellyfinItemKind, str, str | None, datetime | None, bool | None]]


@dataclass(frozen=True, slots=True)
class LibrarySelection:
    """A title's live candidates, narrowed by its remembered pick when that pick survives."""

    item_id: uuid.UUID | None = None
    series_ids: tuple[str, ...] = ()
    ambiguous: bool = False
    pick_dangling: bool = False

    @classmethod
    def from_rows(cls, rows: Sequence[LibraryRow]) -> LibrarySelection:
        """A vanished pick never silently transfers to the remaining candidate."""
        candidates = [row for row in rows if row.removed_at is None and row.kind is not JellyfinItemKind.EPISODE]
        picks = [row for row in rows if row.picked]
        dangling = bool(picks and picks[0].removed_at is not None)
        if picks and not dangling:
            chosen = picks[0]
            series_id = chosen.jellyfin_id if chosen.kind is JellyfinItemKind.SERIES else chosen.series_jellyfin_id
            # An episode with no reported parent cannot narrow the title's exact-id candidates.
            if chosen.kind is not JellyfinItemKind.EPISODE or series_id is not None:
                if chosen.kind is JellyfinItemKind.EPISODE:
                    parent = next((row for row in candidates if row.jellyfin_id == series_id), None)
                    chosen_id = None if parent is None else parent.item_id
                else:
                    chosen_id = chosen.item_id
                return cls(item_id=chosen_id, series_ids=() if series_id is None else (series_id,))
        series_ids = tuple(row.jellyfin_id for row in candidates if row.kind is JellyfinItemKind.SERIES)
        ambiguous = bool(candidates) and (dangling or len(candidates) > 1)
        return cls(
            item_id=candidates[0].item_id if len(candidates) == 1 and not dangling else None,
            series_ids=series_ids,
            ambiguous=ambiguous,
            pick_dangling=dangling,
        )
