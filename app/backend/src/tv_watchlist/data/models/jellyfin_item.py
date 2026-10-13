"""The `tmdb_id -> Jellyfin Id` index `services/library_sync.py` maintains.

A cache, honestly: stale between syncs, rebuilt by one job, never hand-edited - the same standing this
project gives `curated_entry_item` (CLAUDE.md section 5.13). It exists because **Jellyfin has no
provider-id lookup endpoint**: there is no `?tmdbId=` filter, so the only way to answer "is this title
in the library" is to walk `/Items` once, read `ProviderIds` off each row, and keep the answer here.

Three properties are load-bearing rather than incidental:

1. **`jellyfin_id` is the key the sync upserts on**, not `tmdb_id`. Two files can carry the same TMDB id
   (an absolute-numbered rip beside an official one, a remux beside an encode) and that is the whole
   `AMBIGUOUS` case T56 exists to settle - a unique on `tmdb_id` would make the library's real shape
   unstorable.
2. **A vanished file is marked, never deleted.** `title.jellyfin_item_id` may point at this row, and the
   owner's pick has to survive a file being moved and re-indexed. `removed_at` is that mark.
3. **Jellyfin's numbers are carried verbatim.** `parent_index_number`, `index_number` and
   `index_number_end` mean whatever the file naming produced; the ordering they belong to is resolved
   against TheTVDB before any join (CLAUDE.md section 20.2, item 3), never inferred from them here.

Deliberately no `TimestampMixin`. `first_seen_at` and `last_seen_at` already are this table's
`created_at` / `updated_at`, named for what they mean to a library index, and a second pair of the same
two stamps is a column a later reader has to disprove - the reason `watch_event` declines the mixin too.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from tv_watchlist.data.base import Base, UuidPk
from tv_watchlist.data.enums import JellyfinItemKind, pg_enum


class JellyfinItem(UuidPk, Base):
    """One movie, series or episode the owner's own Jellyfin holds, as that server reports it."""

    __tablename__ = "jellyfin_item"
    __table_args__ = (
        UniqueConstraint("jellyfin_id"),
        CheckConstraint("run_time_seconds IS NULL OR run_time_seconds > 0", name="run_time_seconds_positive"),
        # The availability lookup: `(kind, tmdb_id)` is how T51 asks whether a title is in the library.
        Index("ix_jellyfin_item_kind_tmdb_id", "kind", "tmdb_id"),
        # The episode join: every episode of one series, by the series' own Jellyfin id.
        Index("ix_jellyfin_item_series_jellyfin_id", "series_jellyfin_id"),
    )

    # Jellyfin's own item id - a 32-hex or dashed uuid, kept as text because the schema pins neither form.
    jellyfin_id: Mapped[str] = mapped_column(String(64))
    kind: Mapped[JellyfinItemKind] = mapped_column(pg_enum(JellyfinItemKind, "jellyfin_item_kind"))
    name: Mapped[str] = mapped_column(String(500))
    # Nullable: Jellyfin fills `ProviderIds.Tmdb` only when its own scan matched, and an unmatched file is
    # a first-class row - it is what the picker and the unresolved view are for, not an error.
    tmdb_id: Mapped[int | None] = mapped_column(Integer)
    series_jellyfin_id: Mapped[str | None] = mapped_column(String(64))
    parent_index_number: Mapped[int | None] = mapped_column(Integer)
    index_number: Mapped[int | None] = mapped_column(Integer)
    # Non-null means one file covers a range of episodes, so one file satisfies several watch-list rows.
    index_number_end: Mapped[int | None] = mapped_column(Integer)
    # `RunTimeTicks // 10_000_000`, converted once by the DTO at the boundary (CLAUDE.md 11.2, rule 7).
    # There is no ticks column anywhere in this schema, and a reader who finds one has found a bug.
    run_time_seconds: Mapped[int | None] = mapped_column(Integer)
    # The path as Jellyfin reports it, for the picker to show. Free text from the owner's filesystem, so
    # it is rendered as text like any provider field (CLAUDE.md section 10.3, B12).
    path: Mapped[str | None] = mapped_column(String(1000))
    # Jellyfin's `DateLastSaved`, when a server sends one. 12.1's `BaseItemDto` does not declare it, so
    # this is nullable in practice as well as in principle, and the sync never reads a cursor off one row.
    date_last_saved: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # When the sync last WROTE this row. An unchanged row is deliberately not rewritten, so a scan that
    # found nothing new leaves this alone; what a soft delete is computed from is the full scan's seen
    # set, never this column.
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
