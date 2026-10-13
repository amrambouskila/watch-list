"""One TMDB season. Season 0 is the specials bucket and is kept."""

from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Date, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tv_watchlist.data.base import Base, TimestampMixin, UuidPk

if TYPE_CHECKING:
    from tv_watchlist.data.models.episode import Episode
    from tv_watchlist.data.models.title import Title


class Season(UuidPk, TimestampMixin, Base):
    __tablename__ = "season"
    __table_args__ = (
        UniqueConstraint("title_id", "season_number"),
        CheckConstraint("season_number >= 0", name="season_number_non_negative"),
        CheckConstraint("episode_count IS NULL OR episode_count >= 0", name="episode_count_non_negative"),
    )

    title_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("title.id", ondelete="CASCADE"), index=True)
    season_number: Mapped[int] = mapped_column(Integer)
    name: Mapped[str | None] = mapped_column(String(500))
    overview: Mapped[str | None] = mapped_column(Text)
    air_date: Mapped[date | None] = mapped_column(Date)
    episode_count: Mapped[int | None] = mapped_column(Integer)

    title: Mapped[Title] = relationship(back_populates="seasons", lazy="raise_on_sql")
    episodes: Mapped[list[Episode]] = relationship(
        back_populates="season",
        cascade="all, delete-orphan",
        # As on Title.seasons: the FK cascades, so nothing is loaded to be cascaded in Python.
        passive_deletes=True,
        lazy="raise_on_sql",
        order_by="Episode.episode_number",
    )
