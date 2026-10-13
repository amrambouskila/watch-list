"""Durable ownership and recovery journal for one import attempt."""

from __future__ import annotations

import uuid
from typing import Final

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from tv_watchlist.data.base import Base, TimestampMixin, UuidPk
from tv_watchlist.data.enums import MediaImportOperationPhase, MediaImportStatus, pg_enum

ACTIVE_IMPORT_OPERATION: Final[str] = "phase NOT IN ('completed', 'duplicate_skipped', 'failed')"


class MediaImportOperation(UuidPk, TimestampMixin, Base):
    __tablename__ = "media_import_operation"
    __table_args__ = (
        CheckConstraint("source_sha256 ~ '^[0-9a-f]{64}$'", name="source_digest_shape"),
        CheckConstraint(
            "destination_sha256 IS NULL OR destination_sha256 ~ '^[0-9a-f]{64}$'", name="destination_digest_shape"
        ),
        CheckConstraint("verified_sha256 IS NULL OR verified_sha256 ~ '^[0-9a-f]{64}$'", name="verified_digest_shape"),
        CheckConstraint(
            "rollback_status IS NULL OR rollback_status IN ('failed', 'duplicate_skipped')", name="rollback_status"
        ),
        CheckConstraint("(phase = 'rolling_back') = (rollback_status IS NOT NULL)", name="rollback_phase"),
        Index(
            "ix_media_import_operation_active_import",
            "media_import_id",
            unique=True,
            postgresql_where=text(ACTIVE_IMPORT_OPERATION),
        ),
        Index(
            "ix_media_import_operation_active_source",
            "staging_root",
            "source_path",
            unique=True,
            postgresql_where=text(ACTIVE_IMPORT_OPERATION),
        ),
        Index(
            "ix_media_import_operation_active_destination",
            "media_root",
            "destination_path",
            unique=True,
            postgresql_where=text(ACTIVE_IMPORT_OPERATION),
        ),
    )

    media_import_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("media_import.id", ondelete="RESTRICT"))
    phase: Mapped[MediaImportOperationPhase] = mapped_column(
        pg_enum(MediaImportOperationPhase, "media_import_operation_phase")
    )
    staging_root: Mapped[str] = mapped_column(Text)
    media_root: Mapped[str] = mapped_column(Text)
    source_path: Mapped[str] = mapped_column(Text)
    destination_path: Mapped[str] = mapped_column(Text)
    temp_path: Mapped[str] = mapped_column(Text)
    superseded_path: Mapped[str | None] = mapped_column(Text)
    source_identity: Mapped[dict[str, int]] = mapped_column(JSONB)
    destination_identity: Mapped[dict[str, int] | None] = mapped_column(JSONB)
    temp_identity: Mapped[dict[str, int] | None] = mapped_column(JSONB)
    source_sha256: Mapped[str] = mapped_column(String(64))
    destination_sha256: Mapped[str | None] = mapped_column(String(64))
    verified_sha256: Mapped[str | None] = mapped_column(String(64))
    rollback_status: Mapped[MediaImportStatus | None] = mapped_column(pg_enum(MediaImportStatus, "media_import_status"))
    error: Mapped[str | None] = mapped_column(Text)
