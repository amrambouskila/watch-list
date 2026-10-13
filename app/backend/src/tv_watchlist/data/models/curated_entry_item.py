"""The flattened, derived queue: one row per playable unit - an episode of a span, or a movie entry's single slot."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tv_watchlist.data.base import Base, UuidPk

if TYPE_CHECKING:
    from tv_watchlist.data.models.curated_entry import CuratedEntry


class CuratedEntryItem(UuidPk, Base):
    """A cache, honestly: rebuilt delete-then-insert inside the ingest transaction, never hand-edited."""

    __tablename__ = "curated_entry_item"
    __table_args__ = (
        UniqueConstraint("category_id", "absolute_position", deferrable=True, initially="DEFERRED"),
        UniqueConstraint("curated_entry_id", "position_in_entry"),
        CheckConstraint("num_nonnulls(episode_id, movie_title_id) = 1", name="one_playable_unit"),
        CheckConstraint("position_in_entry >= 1", name="position_in_entry_positive"),
        CheckConstraint("absolute_position >= 1", name="absolute_position_positive"),
    )

    category_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("category.id", ondelete="RESTRICT"), index=True)
    curated_entry_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("curated_entry.id", ondelete="CASCADE"), index=True)
    episode_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("episode.id", ondelete="CASCADE"), index=True)
    movie_title_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("title.id", ondelete="CASCADE"))
    position_in_entry: Mapped[int] = mapped_column(Integer)
    absolute_position: Mapped[int] = mapped_column(Integer)

    entry: Mapped[CuratedEntry] = relationship(back_populates="items", lazy="raise_on_sql")
