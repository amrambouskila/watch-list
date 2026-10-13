"""Exact append-only membership of events emitted by one completed file."""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from tv_watchlist.data.base import Base, UuidPk


class PlaybackCompletionEvent(UuidPk, Base):
    __tablename__ = "playback_completion_event"
    __table_args__ = (UniqueConstraint("completion_id", "watch_event_id"),)

    completion_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("playback_completion.id", ondelete="RESTRICT"))
    watch_event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("watch_event.id", ondelete="RESTRICT"), unique=True)
