"""One ingest cursor per provider resource. This IS the provider response cache - there is no Redis."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from tv_watchlist.data.base import Base, TimestampMixin, UuidPk
from tv_watchlist.data.enums import ExternalSource, SyncResourceType, pg_enum


class SyncState(UuidPk, TimestampMixin, Base):
    """`payload_digest` exists because TMDB does not send ETag on every endpoint; equal digest = no write path."""

    __tablename__ = "sync_state"
    __table_args__ = (
        UniqueConstraint("source", "resource_type", "resource_key"),
        CheckConstraint("consecutive_failures >= 0", name="failures_non_negative"),
        Index("ix_sync_state_due", "next_attempt_at", postgresql_where=text("next_attempt_at IS NOT NULL")),
    )

    source: Mapped[ExternalSource] = mapped_column(pg_enum(ExternalSource, "external_source"))
    resource_type: Mapped[SyncResourceType] = mapped_column(pg_enum(SyncResourceType, "sync_resource_type"))
    resource_key: Mapped[str] = mapped_column(String(200))
    etag: Mapped[str | None] = mapped_column(String(200))
    last_modified: Mapped[str | None] = mapped_column(String(64))
    payload_digest: Mapped[str | None] = mapped_column(String(64))
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    last_error: Mapped[str | None] = mapped_column(Text)
