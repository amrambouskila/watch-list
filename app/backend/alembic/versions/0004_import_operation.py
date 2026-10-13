"""Durable import operations, revision 0004 after 0003."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE: Final[str] = "media_import_operation"
_ACTIVE: Final[str] = "phase NOT IN ('completed', 'duplicate_skipped', 'failed')"
_PHASES: Final[tuple[str, ...]] = (
    "prepared",
    "copied",
    "installed",
    "committed",
    "rolling_back",
    "completed",
    "duplicate_skipped",
    "failed",
)
_CHECKS: Final[dict[str, str]] = {
    "source_digest_shape": "source_sha256 ~ '^[0-9a-f]{64}$'",
    "destination_digest_shape": "destination_sha256 IS NULL OR destination_sha256 ~ '^[0-9a-f]{64}$'",
    "verified_digest_shape": "verified_sha256 IS NULL OR verified_sha256 ~ '^[0-9a-f]{64}$'",
    "rollback_status": "rollback_status IS NULL OR rollback_status IN ('failed', 'duplicate_skipped')",
    "rollback_phase": "(phase = 'rolling_back') = (rollback_status IS NOT NULL)",
}
_INDEXES: Final[dict[str, list[str]]] = {
    "ix_media_import_operation_active_import": ["media_import_id"],
    "ix_media_import_operation_active_source": ["staging_root", "source_path"],
    "ix_media_import_operation_active_destination": ["media_root", "destination_path"],
}


def upgrade() -> None:
    postgresql.ENUM(*_PHASES, name="media_import_operation_phase").create(op.get_bind())
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("media_import_id", sa.Uuid(), nullable=False),
        sa.Column(
            "phase", postgresql.ENUM(*_PHASES, name="media_import_operation_phase", create_type=False), nullable=False
        ),
        *(
            sa.Column(name, sa.Text(), nullable=False)
            for name in ("staging_root", "media_root", "source_path", "destination_path", "temp_path")
        ),
        sa.Column("superseded_path", sa.Text()),
        sa.Column("source_identity", postgresql.JSONB(), nullable=False),
        sa.Column("destination_identity", postgresql.JSONB()),
        sa.Column("temp_identity", postgresql.JSONB()),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("destination_sha256", sa.String(64)),
        sa.Column("verified_sha256", sa.String(64)),
        sa.Column("rollback_status", postgresql.ENUM(name="media_import_status", create_type=False)),
        sa.Column("error", sa.Text()),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_media_import_operation")),
        sa.ForeignKeyConstraint(
            ["media_import_id"],
            ["media_import.id"],
            ondelete="RESTRICT",
            name=op.f("fk_media_import_operation_media_import_id_media_import"),
        ),
        *(sa.CheckConstraint(expression, name=op.f(f"ck_{_TABLE}_{name}")) for name, expression in _CHECKS.items()),
    )
    for name, columns in _INDEXES.items():
        op.create_index(name, _TABLE, columns, unique=True, postgresql_where=sa.text(_ACTIVE))


def downgrade() -> None:
    for name in reversed(_INDEXES):
        op.drop_index(name, table_name=_TABLE)
    op.drop_table(_TABLE)
    postgresql.ENUM(name="media_import_operation_phase").drop(op.get_bind())
