"""The append-only log of what the user actually did. The only durable record of progress."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from tv_watchlist.constants import MAX_DEVICE_LENGTH, MAX_NOTE_LENGTH
from tv_watchlist.data.base import Base, UuidPk
from tv_watchlist.data.enums import WatchEventKind, WatchEventSource, WatchSubjectKind, pg_enum


# `tmdb_key` (`movie:603`, `tv:1399:s2:e5`) is the durable pointer that outlives every metadata rebuild.
class WatchEvent(UuidPk, Base):
    """Never updated, never deleted: the watch_event_no_mutation trigger (revision 0001) enforces that."""

    __tablename__ = "watch_event"
    __table_args__ = (
        CheckConstraint("num_nonnulls(episode_id, title_id, curated_entry_id) = 1", name="one_subject"),
        CheckConstraint(
            "(subject_kind = 'episode' AND episode_id IS NOT NULL)"
            " OR (subject_kind = 'title' AND title_id IS NOT NULL)"
            " OR (subject_kind = 'curated_entry' AND curated_entry_id IS NOT NULL)",
            name="kind_matches_column",
        ),
        CheckConstraint("position_seconds IS NULL OR position_seconds >= 0", name="position_seconds_non_negative"),
        CheckConstraint("runtime_seconds IS NULL OR runtime_seconds > 0", name="runtime_seconds_positive"),
        CheckConstraint("kind <> 'progressed' OR position_seconds IS NOT NULL", name="progressed_has_position"),
        # Ordered the way the two DISTINCT ON views read them.
        Index(
            "ix_watch_event_episode_latest",
            "episode_id",
            "occurred_at",
            "recorded_at",
            "id",
            postgresql_where=text("episode_id IS NOT NULL"),
        ),
        Index(
            "ix_watch_event_entry_latest",
            "curated_entry_id",
            "occurred_at",
            "recorded_at",
            "id",
            postgresql_where=text("curated_entry_id IS NOT NULL"),
        ),
        Index(
            "ix_watch_event_title_latest",
            "title_id",
            "occurred_at",
            "recorded_at",
            "id",
            postgresql_where=text("title_id IS NOT NULL"),
        ),
    )

    # Client-supplied and allowed to arrive late; recorded_at is server-assigned; id breaks the last tie.
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    subject_kind: Mapped[WatchSubjectKind] = mapped_column(pg_enum(WatchSubjectKind, "watch_subject_kind"))
    kind: Mapped[WatchEventKind] = mapped_column(pg_enum(WatchEventKind, "watch_event_kind"))
    source: Mapped[WatchEventSource] = mapped_column(pg_enum(WatchEventSource, "watch_event_source"))
    tmdb_key: Mapped[str | None] = mapped_column(String(64), index=True)
    episode_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("episode.id", ondelete="SET NULL"))
    title_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("title.id", ondelete="SET NULL"))
    curated_entry_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("curated_entry.id", ondelete="RESTRICT"))
    category_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("category.id", ondelete="RESTRICT"))
    # Integer seconds, converted once at the boundary (ticks / 10_000_000; currentTime rounded). Never INTERVAL.
    position_seconds: Mapped[int | None] = mapped_column(Integer)
    runtime_seconds: Mapped[int | None] = mapped_column(Integer)
    device: Mapped[str | None] = mapped_column(String(MAX_DEVICE_LENGTH))
    note: Mapped[str | None] = mapped_column(String(MAX_NOTE_LENGTH))
