"""The work - one movie or one series - keyed to TMDB. `(media_type, tmdb_id)` is the Phase 3 join key."""

from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tv_watchlist.data.base import Base, TimestampMixin, UuidPk
from tv_watchlist.data.enums import MediaType, pg_enum

if TYPE_CHECKING:
    from tv_watchlist.data.models.season import Season


class Title(UuidPk, TimestampMixin, Base):
    """Disposable and re-derivable from TMDB; everything below it cascades."""

    __tablename__ = "title"
    __table_args__ = (
        UniqueConstraint("media_type", "tmdb_id"),
        CheckConstraint("runtime_seconds IS NULL OR runtime_seconds > 0", name="runtime_seconds_positive"),
        CheckConstraint("episode_count IS NULL OR episode_count >= 0", name="episode_count_non_negative"),
        CheckConstraint("season_count IS NULL OR season_count >= 0", name="season_count_non_negative"),
        # The fuzzy fallback only; the exact path is the plain btree on match_key.
        Index("ix_title_name_trgm", "name", postgresql_using="gin", postgresql_ops={"name": "gin_trgm_ops"}),
    )

    media_type: Mapped[MediaType] = mapped_column(pg_enum(MediaType, "media_type"))
    # Nullable: a hand-entered local title with no provider match is a first-class record (risk register
    # R2). Postgres treats NULLs as distinct, so uq(media_type, tmdb_id) still holds.
    tmdb_id: Mapped[int | None] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(500))
    original_name: Mapped[str | None] = mapped_column(String(500))
    match_key: Mapped[str] = mapped_column(String(255), index=True)
    overview: Mapped[str | None] = mapped_column(Text)
    first_air_date: Mapped[date | None] = mapped_column(Date)
    last_air_date: Mapped[date | None] = mapped_column(Date)
    runtime_seconds: Mapped[int | None] = mapped_column(Integer)
    episode_count: Mapped[int | None] = mapped_column(Integer)
    season_count: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str | None] = mapped_column(String(60))
    original_language: Mapped[str | None] = mapped_column(String(16))
    # The AMBIGUOUS picker's remembered choice - per TITLE, not per file, so an owner who settles two
    # candidates once is not asked again on every sync (T56). NULL means "no pick made", NEVER "not in
    # library": availability is computed by services/availability.py from (kind, tmdb_id), not read off
    # this column. `ON DELETE SET NULL` because a purged row must not take the title with it - the sync
    # itself only ever soft-deletes, so this fires on a hand purge rather than on a vanished file.
    jellyfin_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jellyfin_item.id", ondelete="SET NULL"))

    seasons: Mapped[list[Season]] = relationship(
        back_populates="title",
        cascade="all, delete-orphan",
        # The database's ON DELETE CASCADE does the work; loading the collection to cascade in Python is
        # exactly what raise_on_sql forbids.
        passive_deletes=True,
        lazy="raise_on_sql",
        order_by="Season.season_number",
    )
