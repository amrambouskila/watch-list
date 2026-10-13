"""The projection of one workbook file."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tv_watchlist.data.base import Base, TimestampMixin, UuidPk

if TYPE_CHECKING:
    from tv_watchlist.data.models.curated_entry import CuratedEntry


class Category(UuidPk, TimestampMixin, Base):
    """One `.xlsx`. Excel owns its order and curation; this row owns the ingest cursors."""

    __tablename__ = "category"
    __table_args__ = (CheckConstraint("accent ~ '^#[0-9A-Fa-f]{6}$'", name="accent_hex"),)

    slug: Mapped[str] = mapped_column(String(200), unique=True)
    file_name: Mapped[str] = mapped_column(String(255))
    sheet_title: Mapped[str] = mapped_column(String(255))
    accent: Mapped[str] = mapped_column(String(7))
    identity_column_key: Mapped[str | None] = mapped_column(String(120))
    # The same st_mtime float the live API carries (CategorySummary.mtime); re-typing it would fork a contract.
    workbook_mtime: Mapped[float | None] = mapped_column(Float)
    workbook_digest: Mapped[str | None] = mapped_column(String(64))
    last_ingested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_mirrored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_ingest_error: Mapped[str | None] = mapped_column(Text)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    entries: Mapped[list[CuratedEntry]] = relationship(
        back_populates="category", lazy="raise_on_sql", order_by="CuratedEntry.position"
    )
