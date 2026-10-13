"""The projection of one sheet data row - the heart of the model."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tv_watchlist.data.base import Base, TimestampMixin, UuidPk
from tv_watchlist.data.enums import ResolutionState, UnitKind, pg_enum

if TYPE_CHECKING:
    from tv_watchlist.data.models.category import Category
    from tv_watchlist.data.models.curated_entry_item import CuratedEntryItem
    from tv_watchlist.data.models.title import Title


class CuratedEntry(UuidPk, TimestampMixin, Base):
    """One row of one workbook. `id` is the UUID written back into the sheet's hidden `Row ID` column."""

    __tablename__ = "curated_entry"
    __table_args__ = (
        # Deferrable so a whole category renumbers in one UPDATE without tripping on transient duplicates.
        UniqueConstraint("category_id", "position", deferrable=True, initially="DEFERRED"),
        CheckConstraint("position >= 1", name="position_positive"),
        CheckConstraint("sheet_row IS NULL OR sheet_row >= 2", name="sheet_row_below_header"),
        CheckConstraint("span_start IS NULL OR span_start >= 1", name="span_start_positive"),
        CheckConstraint("span_end IS NULL OR span_end >= 1", name="span_end_positive"),
        CheckConstraint("span_start IS NULL OR span_end IS NULL OR span_end >= span_start", name="span_ordered"),
        CheckConstraint("season_number IS NULL OR season_number >= 0", name="season_number_non_negative"),
        CheckConstraint(
            "resolution_confidence IS NULL OR (resolution_confidence >= 0 AND resolution_confidence <= 1)",
            name="confidence_unit_interval",
        ),
        Index(
            "ix_curated_entry_needs_review",
            "category_id",
            "position",
            postgresql_where=text("removed_at IS NULL AND resolution_state IN ('unresolved', 'auto')"),
        ),
    )

    category_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("category.id", ondelete="RESTRICT"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    sheet_row: Mapped[int | None] = mapped_column(Integer)
    title_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("title.id", ondelete="SET NULL"), index=True)
    # server_default as well as default, so a raw INSERT (a data migration, a psql session) does not fail.
    unit_kind: Mapped[UnitKind] = mapped_column(
        pg_enum(UnitKind, "unit_kind"), default=UnitKind.UNKNOWN, server_default=UnitKind.UNKNOWN.value
    )
    # Open string: the numbering a row names may be one TheTVDB adds tomorrow (master plan 10.1).
    order_type: Mapped[str | None] = mapped_column(String(32))
    order_label: Mapped[str] = mapped_column(String(120), default="", server_default="")
    span_start: Mapped[int | None] = mapped_column(Integer)
    span_end: Mapped[int | None] = mapped_column(Integer)
    season_number: Mapped[int | None] = mapped_column(Integer)
    resolution_state: Mapped[ResolutionState] = mapped_column(
        pg_enum(ResolutionState, "resolution_state"),
        default=ResolutionState.UNRESOLVED,
        server_default=ResolutionState.UNRESOLVED.value,
        index=True,
    )
    resolution_confidence: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))
    resolution_note: Mapped[str] = mapped_column(Text, default="", server_default="")
    # The verbatim row: nineteen workbooks with different headers would otherwise need nineteen schemas.
    raw_cells: Mapped[dict[str, str]] = mapped_column(JSONB)
    raw_title: Mapped[str] = mapped_column(Text, default="", server_default="")
    raw_unit: Mapped[str] = mapped_column(Text, default="", server_default="")
    raw_release: Mapped[str] = mapped_column(Text, default="", server_default="")
    match_key: Mapped[str | None] = mapped_column(String(255), index=True)
    observed_watch_cell: Mapped[str] = mapped_column(String(32), default="", server_default="")
    mirrored_watch_cell: Mapped[str] = mapped_column(String(32), default="", server_default="")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    category: Mapped[Category] = relationship(back_populates="entries", lazy="raise_on_sql")
    title: Mapped[Title | None] = relationship(lazy="raise_on_sql")
    items: Mapped[list[CuratedEntryItem]] = relationship(
        back_populates="entry", lazy="raise_on_sql", order_by="CuratedEntryItem.position_in_entry"
    )
