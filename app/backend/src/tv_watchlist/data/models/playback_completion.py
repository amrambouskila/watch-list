"""Immutable evidence of one completed file and its curated context."""

from __future__ import annotations

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from tv_watchlist.data.base import Base, UuidPk


class PlaybackCompletion(UuidPk, Base):
    __tablename__ = "playback_completion"
    __table_args__ = (
        CheckConstraint("length(btrim(jellyfin_id_snapshot)) > 0", name="jellyfin_id_nonempty"),
        CheckConstraint("queue_fingerprint ~ '^[0-9a-f]{64}$'", name="queue_fingerprint_shape"),
        CheckConstraint("jsonb_typeof(occurrence_snapshot) = 'array'", name="occurrence_snapshot_array"),
        CheckConstraint(
            "(parent_index_number IS NULL OR parent_index_number >= 0)"
            " AND (index_number IS NULL OR index_number >= 0)"
            " AND (index_number_end IS NULL OR index_number_end >= 0)",
            name="indices_nonnegative",
        ),
        CheckConstraint(
            "index_number_end IS NULL OR (index_number IS NOT NULL AND index_number_end >= index_number)",
            name="index_range",
        ),
        CheckConstraint(
            "(order_type IS NULL AND order_label = '' AND parent_index_number IS NULL"
            " AND index_number IS NULL AND index_number_end IS NULL)"
            " OR (order_type IS NOT NULL AND length(btrim(order_type)) > 0"
            " AND parent_index_number IS NOT NULL AND index_number IS NOT NULL)",
            name="numbering_shape",
        ),
    )

    selected_watch_event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("watch_event.id", ondelete="RESTRICT"), unique=True
    )
    category_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("category.id", ondelete="RESTRICT"), index=True)
    source_entry_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("curated_entry.id", ondelete="RESTRICT"), index=True)
    jellyfin_item_id_snapshot: Mapped[uuid.UUID]
    jellyfin_id_snapshot: Mapped[str] = mapped_column(String(64))
    order_type: Mapped[str | None] = mapped_column(String(32))
    order_label: Mapped[str] = mapped_column(String(120), default="", server_default="")
    parent_index_number: Mapped[int | None] = mapped_column(Integer)
    index_number: Mapped[int | None] = mapped_column(Integer)
    index_number_end: Mapped[int | None] = mapped_column(Integer)
    queue_fingerprint: Mapped[str] = mapped_column(String(64))
    occurrence_snapshot: Mapped[list[dict[str, str | int | None]]] = mapped_column(JSONB)
