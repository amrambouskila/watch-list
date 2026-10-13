"""One episode's slot in one numbering of one title. `sequence` is a dense 1-based rank within that numbering."""

from __future__ import annotations

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from tv_watchlist.data.base import Base, TimestampMixin, UuidPk
from tv_watchlist.data.enums import ExternalSource, pg_enum


# dvd: renumbered, which is why order_season_number / order_episode_number sit beside the rank -
# they are what the UI prints; sequence is what the app computes with.
class EpisodeOrder(UuidPk, TimestampMixin, Base):
    """absolute: sequence IS the number. aired: ranked over (season, episode) with season 0 excluded."""

    __tablename__ = "episode_order"
    __table_args__ = (
        UniqueConstraint("title_id", "order_type", "label", "sequence", deferrable=True, initially="DEFERRED"),
        UniqueConstraint("episode_id", "order_type", "label"),
        CheckConstraint("sequence >= 1", name="sequence_positive"),
        CheckConstraint("order_season_number IS NULL OR order_season_number >= 0", name="order_season_non_negative"),
        CheckConstraint("order_episode_number IS NULL OR order_episode_number >= 0", name="order_episode_non_negative"),
    )

    title_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("title.id", ondelete="CASCADE"), index=True)
    episode_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("episode.id", ondelete="CASCADE"), index=True)
    # An open string, never an enum: TheTVDB's season types are read at runtime and the set is not closed.
    order_type: Mapped[str] = mapped_column(String(32))
    label: Mapped[str] = mapped_column(String(120), default="", server_default="")
    sequence: Mapped[int] = mapped_column(Integer)
    order_season_number: Mapped[int | None] = mapped_column(Integer)
    order_episode_number: Mapped[int | None] = mapped_column(Integer)
    # TMDB and TheTVDB disagree; the app must be able to say which one it is showing.
    source: Mapped[ExternalSource] = mapped_column(pg_enum(ExternalSource, "external_source"))
