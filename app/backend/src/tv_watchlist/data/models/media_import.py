"""One file's journey from where the owner put it to where Jellyfin found it. Never deleted; superseded.

Phase 3.5's provenance table (ADR-015, T61): every file the import pipeline has ever found, staged,
identified, moved or hashed, whether it came from the staging folder, a completed qBittorrent download, or
the owner's own hand. Nothing here is ever deleted - a re-import supersedes the row it replaces
(`superseded_at` / `superseded_by_id`), so the history of what happened to a file survives the file itself
moving, being re-hashed, or being replaced by a better copy.

Three parents may vanish out from under a row without taking it with them: a title re-resolved, an episode
re-ingested, a Jellyfin item purged. Each foreign key is `ON DELETE SET NULL` for exactly that reason - the
provenance record is worth more than the pointer, matching the standing this project already gives
`jellyfin_item` and `curated_entry_item` (CLAUDE.md section 5.13).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Final

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Float, ForeignKey, Index, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tv_watchlist.data.base import Base, TimestampMixin, UuidPk
from tv_watchlist.data.enums import MediaImportIdentifiedBy, MediaImportSource, MediaImportStatus, pg_enum

if TYPE_CHECKING:
    from tv_watchlist.data.models.title import Title

# The three statuses that mean "the file landed on disk" - shared between the CHECK and the partial index
# so the two can never drift apart on which statuses count as "moved".
_LIVE_STATUSES: Final[str] = "'moved', 'hashed', 'refreshed'"


class MediaImport(UuidPk, TimestampMixin, Base):
    """One file's provenance record: where it was found, what it was matched to, where it landed."""

    __tablename__ = "media_import"
    __table_args__ = (
        CheckConstraint("size_bytes > 0", name="size_positive"),
        CheckConstraint("file_sha256 IS NULL OR char_length(file_sha256) = 64", name="sha256_shape"),
        CheckConstraint(
            "identification_confidence IS NULL OR (identification_confidence >= 0 AND identification_confidence <= 1)",
            name="confidence_range",
        ),
        # Ruling 100: `title_id` is metadata and cascades freely (CLAUDE.md 5.13's deletion policy) - it
        # cannot be the thing a status-based CHECK requires, or a title purge behind a `moved` row would
        # be refused rather than nulling cleanly, which the ON DELETE SET NULL on `title_id` promises.
        # `identified_by` is what a CHECK may safely require instead: it is a plain enum column no parent
        # delete can touch, so the invariant it states - a row past identification always records HOW it
        # was identified - survives for the row's whole life, even after the title itself is later purged.
        # The companion invariant, that an identified-or-later row also HAS a title, moves to the write
        # path (services/import_identify.py, T65) rather than a database CHECK a legitimate purge would trip.
        CheckConstraint(
            "status IN ('found', 'unidentified', 'failed') OR identified_by IS NOT NULL",
            name="identified_records_how",
        ),
        CheckConstraint(f"status NOT IN ({_LIVE_STATUSES}) OR file_path IS NOT NULL", name="moved_has_path"),
        CheckConstraint("status NOT IN ('hashed', 'refreshed') OR file_sha256 IS NOT NULL", name="hashed_has_digest"),
        # R76: a row that stopped - failed, or could not be identified - with no reason is an unanswerable
        # support question. Covers both, not `failed` alone.
        CheckConstraint("status NOT IN ('failed', 'unidentified') OR error IS NOT NULL", name="stopped_has_error"),
        CheckConstraint("(superseded_at IS NULL) = (superseded_by_id IS NULL)", name="superseded_pair"),
        CheckConstraint("superseded_by_id IS NULL OR superseded_by_id <> id", name="not_self_superseded"),
        # The database fact behind `duplicate_skipped`: a superseded row keeps its digest without blocking
        # the row that replaced it, so the partial predicate excludes anything already superseded.
        Index(
            "ix_media_import_live_sha256",
            "file_sha256",
            unique=True,
            postgresql_where=text(
                f"file_sha256 IS NOT NULL AND superseded_at IS NULL AND status IN ({_LIVE_STATUSES})"
            ),
        ),
        # The paged `GET /api/imports` list.
        Index("ix_media_import_status_found_at", "status", "found_at"),
        # The scan's "have I already seen this path" question.
        Index("ix_media_import_source_path", "source_path"),
    )

    # Null until identified. SET NULL rather than CASCADE or RESTRICT: a title re-resolved or purged must
    # not take this row's history with it.
    title_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("title.id", ondelete="SET NULL"), index=True)
    # Null for a film, and null until the episode itself is ingested.
    episode_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("episode.id", ondelete="SET NULL"), index=True)
    # Set once the sync maps this file into the library index.
    jellyfin_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("jellyfin_item.id", ondelete="SET NULL"), index=True
    )
    source: Mapped[MediaImportSource] = mapped_column(pg_enum(MediaImportSource, "media_import_source"))
    # Where the scan found it, verbatim: a staging path, or a qBittorrent save_path/name join.
    source_path: Mapped[str] = mapped_column(Text)
    # The source basename before any renaming - what the owner actually downloaded or dropped in.
    original_name: Mapped[str] = mapped_column(String(500))
    # BigInteger, not Integer: a 4K remux or a Blu-ray rip routinely exceeds 2 GiB, which is exactly where
    # a plain int4 column overflows. A provenance table for video files that silently refused anything
    # over 2 GiB on day one would be a bug, not a simplification.
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    # RELATIVE to the media root, POSIX separators - null before the move lands.
    file_path: Mapped[str | None] = mapped_column(Text)
    file_sha256: Mapped[str | None] = mapped_column(String(64))
    identified_by: Mapped[MediaImportIdentifiedBy | None] = mapped_column(
        pg_enum(MediaImportIdentifiedBy, "media_import_identified_by")
    )
    identification_confidence: Mapped[float | None] = mapped_column(Float)
    # No server_default: a row is always created by the scan with an explicit status, never one Postgres
    # invents for it.
    status: Mapped[MediaImportStatus] = mapped_column(pg_enum(MediaImportStatus, "media_import_status"))
    # Why the row stopped: a failure's reason, or why identification did not match, for an `unidentified` row.
    error: Mapped[str | None] = mapped_column(Text)
    found_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    imported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The row that replaced this one. RESTRICT, not CASCADE or SET NULL: a superseding row is never
    # removed while another row still points at it as the reason it stopped mattering.
    superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("media_import.id", ondelete="RESTRICT"))

    # `MediaImportRead.title_name` is the only reason this exists; nothing else reads it yet.
    title: Mapped[Title | None] = relationship(lazy="raise_on_sql")

    @property
    def title_name(self) -> str | None:
        """Derived, never stored. Raises rather than lazy-loading if `title` was not `selectinload()`ed."""
        return None if self.title is None else self.title.name
