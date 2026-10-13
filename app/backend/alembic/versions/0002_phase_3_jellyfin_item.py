"""phase 3 jellyfin item

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-23 01:17:01.028497

The Phase 3 library index (T49): one table, one nullable column on `title`, one native enum.

Hand-ordered, exactly as 0001 is, because autogenerate gets two things wrong here. It emits the enum
inline on `create_table` with SQLAlchemy's own `create_type=True`, which is not how this schema declares
types - `pg_enum` sets `create_type=False` so a type shared by several tables is created once, by name,
where a reader can see it. And its `downgrade` drops the table while leaving the type behind, which makes
`downgrade base` -> `upgrade head` fail on the second pass with "type already exists".
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen here on purpose, never imported from data/enums.py: a later member gets its own revision rather
# than silently rewriting what this one already ran against a live database.
ENUMS: Final[dict[str, tuple[str, ...]]] = {"jellyfin_item_kind": ("movie", "series", "episode")}

_TABLE: Final[str] = "jellyfin_item"
_KIND_TMDB_INDEX: Final[str] = "ix_jellyfin_item_kind_tmdb_id"
_SERIES_INDEX: Final[str] = "ix_jellyfin_item_series_jellyfin_id"
_PICK_COLUMN: Final[str] = "jellyfin_item_id"


def _enum(name: str) -> postgresql.ENUM:
    """The type as a column reference only; upgrade() creates it once, by hand, above."""
    return postgresql.ENUM(*ENUMS[name], name=name, create_type=False)


def _create_type(name: str, labels: tuple[str, ...]) -> str:
    """CREATE TYPE takes no bind parameters; every label here is a literal declared a few lines above."""
    members = ", ".join(f"'{label}'" for label in labels)
    return f"CREATE TYPE {name} AS ENUM ({members})"


def _jellyfin_item() -> None:
    op.create_table(
        _TABLE,
        sa.Column("jellyfin_id", sa.String(64), nullable=False),
        sa.Column("kind", _enum("jellyfin_item_kind"), nullable=False),
        sa.Column("name", sa.String(500), nullable=False),
        # Nullable: Jellyfin fills ProviderIds.Tmdb only when its own scan matched, and an unmatched file
        # is a first-class row rather than an error.
        sa.Column("tmdb_id", sa.Integer),
        sa.Column("series_jellyfin_id", sa.String(64)),
        # Jellyfin's own numbers, verbatim. IndexNumberEnd non-null means one file covers a range.
        sa.Column("parent_index_number", sa.Integer),
        sa.Column("index_number", sa.Integer),
        sa.Column("index_number_end", sa.Integer),
        # RunTimeTicks // 10_000_000, converted once at the DTO boundary. There is no ticks column.
        sa.Column("run_time_seconds", sa.Integer),
        sa.Column("path", sa.String(1000)),
        sa.Column("date_last_saved", sa.DateTime(timezone=True)),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        # Soft delete: title.jellyfin_item_id may point here, so a vanished file is marked, never deleted.
        sa.Column("removed_at", sa.DateTime(timezone=True)),
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.CheckConstraint(
            "run_time_seconds IS NULL OR run_time_seconds > 0",
            name=op.f("ck_jellyfin_item_run_time_seconds_positive"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jellyfin_item")),
        # The upsert key. NOT tmdb_id: two files may carry one TMDB id, and that is the AMBIGUOUS case.
        sa.UniqueConstraint("jellyfin_id", name=op.f("uq_jellyfin_item_jellyfin_id")),
    )
    op.create_index(_KIND_TMDB_INDEX, _TABLE, ["kind", "tmdb_id"], unique=False)
    op.create_index(_SERIES_INDEX, _TABLE, ["series_jellyfin_id"], unique=False)


def _title_pick() -> None:
    """The AMBIGUOUS picker's remembered choice, per title. NULL is "no pick", never "not in library"."""
    op.add_column("title", sa.Column(_PICK_COLUMN, sa.Uuid(as_uuid=True)))
    op.create_foreign_key(
        op.f("fk_title_jellyfin_item_id_jellyfin_item"),
        "title",
        _TABLE,
        [_PICK_COLUMN],
        ["id"],
        ondelete="SET NULL",
    )


def upgrade() -> None:
    """Upgrade schema."""
    for name, labels in ENUMS.items():
        op.execute(_create_type(name, labels))
    _jellyfin_item()
    # After the table it points at, so the foreign key has something to reference.
    _title_pick()


def downgrade() -> None:
    """Downgrade schema."""
    # Hand-ordered: the foreign key and its column go before the table they reference, and the type goes
    # after both - a native enum left behind makes the next `upgrade head` fail on "type already exists".
    op.drop_constraint(op.f("fk_title_jellyfin_item_id_jellyfin_item"), "title", type_="foreignkey")
    op.drop_column("title", _PICK_COLUMN)
    op.drop_index(_SERIES_INDEX, table_name=_TABLE)
    op.drop_index(_KIND_TMDB_INDEX, table_name=_TABLE)
    op.drop_table(_TABLE)
    for name in reversed(ENUMS):
        op.execute(f"DROP TYPE {name}")
