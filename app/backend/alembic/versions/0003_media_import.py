"""media import provenance

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-23 00:00:00.000000

Phase 3.5's provenance table (ADR-015, T61): one table, three native enums, and the FK ordering the table
demands - `media_import.jellyfin_item_id` references `jellyfin_item.id`, so this revision can only ever
follow T49's (0002), never precede it.

Hand-ordered, exactly as 0001 and 0002 are, for the same two reasons autogenerate always gets wrong here.
It emits each enum inline on `create_table` with SQLAlchemy's own `create_type=True`, which is not how
this schema declares types - `pg_enum` sets `create_type=False` so a type is created once, by name, where
a reader can see it, and a `downgrade` that dropped the table while leaving the three types behind would
make the NEXT `upgrade head` fail on "type already exists" - a failure that a single-step `downgrade -1`
would never surface.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen here on purpose, never imported from data/enums.py: a later member gets its own revision rather
# than silently rewriting what this one already ran against a live database.
ENUMS: Final[dict[str, tuple[str, ...]]] = {
    "media_import_source": ("staging_folder", "qbittorrent_completed", "manual"),
    "media_import_identified_by": ("filename", "owner_pick"),
    "media_import_status": (
        "found",
        "identified",
        "moved",
        "hashed",
        "refreshed",
        "failed",
        "duplicate_skipped",
        "unidentified",
    ),
}

_TABLE: Final[str] = "media_import"
# The three statuses that mean "the file landed on disk" - matches the constant of the same name in
# data/models/media_import.py, so the CHECK and the partial index can never drift on which count as "moved".
_LIVE_STATUSES: Final[str] = "'moved', 'hashed', 'refreshed'"


def _enum(name: str) -> postgresql.ENUM:
    """The type as a column reference only; upgrade() creates it once, by hand, above."""
    return postgresql.ENUM(*ENUMS[name], name=name, create_type=False)


def _create_type(name: str, labels: tuple[str, ...]) -> str:
    """CREATE TYPE takes no bind parameters; every label here is a literal declared a few lines above."""
    members = ", ".join(f"'{label}'" for label in labels)
    return f"CREATE TYPE {name} AS ENUM ({members})"


def _fk(table: str, column: str, target: str, ondelete: str) -> sa.Column[sa.Uuid]:
    """A nullable, typed foreign key carrying the name the metadata's naming convention would mint for it."""
    referred = target.split(".", 1)[0]
    return sa.Column(
        column,
        sa.Uuid(as_uuid=True),
        sa.ForeignKey(target, ondelete=ondelete, name=op.f(f"fk_{table}_{column}_{referred}")),
    )


def _media_import() -> None:
    op.create_table(
        _TABLE,
        # Null until identified. SET NULL, not CASCADE or RESTRICT: a title re-resolved or purged must not
        # take this row's history with it.
        _fk(_TABLE, "title_id", "title.id", "SET NULL"),
        # Null for a film, and null until the episode itself is ingested.
        _fk(_TABLE, "episode_id", "episode.id", "SET NULL"),
        # Set once the sync maps this file into the library index.
        _fk(_TABLE, "jellyfin_item_id", "jellyfin_item.id", "SET NULL"),
        sa.Column("source", _enum("media_import_source"), nullable=False),
        # Where the scan found it, verbatim: a staging path, or a qBittorrent save_path/name join.
        sa.Column("source_path", sa.Text, nullable=False),
        # The source basename before any renaming - what the owner actually downloaded or dropped in.
        sa.Column("original_name", sa.String(500), nullable=False),
        # BigInteger, not Integer: a 4K remux or a Blu-ray rip routinely exceeds 2 GiB, exactly where a
        # plain int4 column overflows.
        sa.Column("size_bytes", sa.BigInteger, nullable=False),
        # RELATIVE to the media root, POSIX separators - null before the move lands.
        sa.Column("file_path", sa.Text),
        sa.Column("file_sha256", sa.String(64)),
        sa.Column("identified_by", _enum("media_import_identified_by")),
        sa.Column("identification_confidence", sa.Float),
        # No server_default: a row is always created by the scan with an explicit status.
        sa.Column("status", _enum("media_import_status"), nullable=False),
        sa.Column("error", sa.Text),
        sa.Column("found_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True)),
        sa.Column("superseded_at", sa.DateTime(timezone=True)),
        # The row that replaced this one. RESTRICT: a superseding row is never removed while another row
        # still points at it as the reason it stopped mattering.
        _fk(_TABLE, "superseded_by_id", f"{_TABLE}.id", "RESTRICT"),
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{_TABLE}")),
        sa.CheckConstraint("size_bytes > 0", name=op.f(f"ck_{_TABLE}_size_positive")),
        sa.CheckConstraint(
            "file_sha256 IS NULL OR char_length(file_sha256) = 64", name=op.f(f"ck_{_TABLE}_sha256_shape")
        ),
        sa.CheckConstraint(
            "identification_confidence IS NULL OR (identification_confidence >= 0 AND identification_confidence <= 1)",
            name=op.f(f"ck_{_TABLE}_confidence_range"),
        ),
        # Ruling 100: `identified_by` is a plain enum column no parent delete can touch, so this survives
        # a title purge intact - unlike `title_id`, which is metadata and must be free to go SET NULL
        # without the row's own CHECK refusing the delete. The companion "and has a title" half moves to
        # the write path (services/import_identify.py, T65) rather than a database CHECK a legitimate
        # purge would trip.
        sa.CheckConstraint(
            "status IN ('found', 'unidentified', 'failed') OR identified_by IS NOT NULL",
            name=op.f(f"ck_{_TABLE}_identified_records_how"),
        ),
        sa.CheckConstraint(
            f"status NOT IN ({_LIVE_STATUSES}) OR file_path IS NOT NULL", name=op.f(f"ck_{_TABLE}_moved_has_path")
        ),
        sa.CheckConstraint(
            "status NOT IN ('hashed', 'refreshed') OR file_sha256 IS NOT NULL",
            name=op.f(f"ck_{_TABLE}_hashed_has_digest"),
        ),
        # R76: covers both `failed` and `unidentified`, not `failed` alone.
        sa.CheckConstraint(
            "status NOT IN ('failed', 'unidentified') OR error IS NOT NULL",
            name=op.f(f"ck_{_TABLE}_stopped_has_error"),
        ),
        sa.CheckConstraint(
            "(superseded_at IS NULL) = (superseded_by_id IS NULL)", name=op.f(f"ck_{_TABLE}_superseded_pair")
        ),
        sa.CheckConstraint(
            "superseded_by_id IS NULL OR superseded_by_id <> id", name=op.f(f"ck_{_TABLE}_not_self_superseded")
        ),
    )
    op.create_index(op.f("ix_media_import_title_id"), _TABLE, ["title_id"])
    op.create_index(op.f("ix_media_import_episode_id"), _TABLE, ["episode_id"])
    op.create_index(op.f("ix_media_import_jellyfin_item_id"), _TABLE, ["jellyfin_item_id"])
    # The database fact behind `duplicate_skipped`: a superseded row keeps its digest without blocking the
    # row that replaced it.
    op.create_index(
        "ix_media_import_live_sha256",
        _TABLE,
        ["file_sha256"],
        unique=True,
        postgresql_where=sa.text(f"file_sha256 IS NOT NULL AND superseded_at IS NULL AND status IN ({_LIVE_STATUSES})"),
    )
    # The paged `GET /api/imports` list.
    op.create_index("ix_media_import_status_found_at", _TABLE, ["status", "found_at"])
    # The scan's "have I already seen this path" question.
    op.create_index("ix_media_import_source_path", _TABLE, ["source_path"])


def upgrade() -> None:
    """Upgrade schema."""
    for name, labels in ENUMS.items():
        op.execute(_create_type(name, labels))
    _media_import()


def downgrade() -> None:
    """Downgrade schema."""
    # Hand-ordered: the table goes before the three types it uses - a native enum left behind makes the
    # next `upgrade head` fail on "type already exists".
    op.drop_index("ix_media_import_source_path", table_name=_TABLE)
    op.drop_index("ix_media_import_status_found_at", table_name=_TABLE)
    op.drop_index("ix_media_import_live_sha256", table_name=_TABLE)
    op.drop_index(op.f("ix_media_import_jellyfin_item_id"), table_name=_TABLE)
    op.drop_index(op.f("ix_media_import_episode_id"), table_name=_TABLE)
    op.drop_index(op.f("ix_media_import_title_id"), table_name=_TABLE)
    op.drop_table(_TABLE)
    for name in reversed(ENUMS):
        op.execute(f"DROP TYPE {name}")
