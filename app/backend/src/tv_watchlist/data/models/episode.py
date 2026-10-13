"""One episode. `title_id` is denormalised on purpose so every order query stays a single join."""

from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Date, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tv_watchlist.data.base import Base, TimestampMixin, UuidPk

if TYPE_CHECKING:
    from tv_watchlist.data.models.season import Season


# TMDB numbers anime absolutely inside season buckets, so rendering goes through episode_order
# (CLAUDE.md section 11, rule 9).
class Episode(UuidPk, TimestampMixin, Base):
    """`(season_number, episode_number)` is a key, NOT a human SxxEyy."""

    __tablename__ = "episode"
    __table_args__ = (
        UniqueConstraint("season_id", "episode_number"),
        UniqueConstraint("tmdb_episode_id"),
        CheckConstraint("season_number >= 0", name="season_number_non_negative"),
        CheckConstraint("episode_number >= 0", name="episode_number_non_negative"),
        CheckConstraint("runtime_seconds IS NULL OR runtime_seconds > 0", name="runtime_seconds_positive"),
    )

    # Both copies are written in the same ingest transaction; `episode.title_id = season.title_id` is
    # asserted by the ingest test suite because a CHECK cannot express a cross-table invariant.
    title_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("title.id", ondelete="CASCADE"), index=True)
    season_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("season.id", ondelete="CASCADE"), index=True)
    season_number: Mapped[int] = mapped_column(Integer)
    episode_number: Mapped[int] = mapped_column(Integer)
    tmdb_episode_id: Mapped[int] = mapped_column(Integer)
    name: Mapped[str | None] = mapped_column(String(500))
    overview: Mapped[str | None] = mapped_column(Text)
    air_date: Mapped[date | None] = mapped_column(Date)
    runtime_seconds: Mapped[int | None] = mapped_column(Integer)
    production_code: Mapped[str | None] = mapped_column(String(60))

    season: Mapped[Season] = relationship(back_populates="episodes", lazy="raise_on_sql")
