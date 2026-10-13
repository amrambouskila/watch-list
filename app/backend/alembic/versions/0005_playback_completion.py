"""Immutable file-completion history, revision 0005 after 0004."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RECEIPT: Final[str] = "playback_completion"
_MEMBERSHIP: Final[str] = "playback_completion_event"
_CHECKS: Final[dict[str, str]] = {
    "jellyfin_id_nonempty": "length(btrim(jellyfin_id_snapshot)) > 0",
    "queue_fingerprint_shape": "queue_fingerprint ~ '^[0-9a-f]{64}$'",
    "occurrence_snapshot_array": "jsonb_typeof(occurrence_snapshot) = 'array'",
    "indices_nonnegative": "(parent_index_number IS NULL OR parent_index_number >= 0)"
    " AND (index_number IS NULL OR index_number >= 0)"
    " AND (index_number_end IS NULL OR index_number_end >= 0)",
    "index_range": "index_number_end IS NULL OR (index_number IS NOT NULL AND index_number_end >= index_number)",
    "numbering_shape": "(order_type IS NULL AND order_label = '' AND parent_index_number IS NULL"
    " AND index_number IS NULL AND index_number_end IS NULL)"
    " OR (order_type IS NOT NULL AND length(btrim(order_type)) > 0"
    " AND parent_index_number IS NOT NULL AND index_number IS NOT NULL)",
}
_REFUSE_MUTATION: Final[str] = """
CREATE FUNCTION playback_completion_reject_mutation() RETURNS trigger
LANGUAGE plpgsql AS $fn$
BEGIN
    RAISE EXCEPTION '% is append-only (attempted %)', TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$fn$
"""


def upgrade() -> None:
    op.create_table(
        _RECEIPT,
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("selected_watch_event_id", sa.Uuid(), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.Column("source_entry_id", sa.Uuid(), nullable=False),
        sa.Column("jellyfin_item_id_snapshot", sa.Uuid(), nullable=False),
        sa.Column("jellyfin_id_snapshot", sa.String(64), nullable=False),
        sa.Column("order_type", sa.String(32)),
        sa.Column("order_label", sa.String(120), server_default="", nullable=False),
        sa.Column("parent_index_number", sa.Integer()),
        sa.Column("index_number", sa.Integer()),
        sa.Column("index_number_end", sa.Integer()),
        sa.Column("queue_fingerprint", sa.String(64), nullable=False),
        sa.Column("occurrence_snapshot", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_playback_completion")),
        sa.UniqueConstraint("selected_watch_event_id", name=op.f("uq_playback_completion_selected_watch_event_id")),
        *(
            sa.ForeignKeyConstraint(
                [column], [target], ondelete="RESTRICT", name=op.f(f"fk_{_RECEIPT}_{column}_{target.split('.')[0]}")
            )
            for column, target in (
                ("selected_watch_event_id", "watch_event.id"),
                ("category_id", "category.id"),
                ("source_entry_id", "curated_entry.id"),
            )
        ),
        *(sa.CheckConstraint(expression, name=op.f(f"ck_{_RECEIPT}_{name}")) for name, expression in _CHECKS.items()),
    )
    for column in ("category_id", "source_entry_id"):
        op.create_index(f"ix_{_RECEIPT}_{column}", _RECEIPT, [column])
    op.create_table(
        _MEMBERSHIP,
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("completion_id", sa.Uuid(), nullable=False),
        sa.Column("watch_event_id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_playback_completion_event")),
        sa.UniqueConstraint("watch_event_id", name=op.f("uq_playback_completion_event_watch_event_id")),
        sa.UniqueConstraint(
            "completion_id", "watch_event_id", name=op.f("uq_playback_completion_event_completion_id_watch_event_id")
        ),
        sa.ForeignKeyConstraint(
            ["completion_id"],
            ["playback_completion.id"],
            ondelete="RESTRICT",
            name=op.f("fk_playback_completion_event_completion_id_playback_completion"),
        ),
        sa.ForeignKeyConstraint(
            ["watch_event_id"],
            ["watch_event.id"],
            ondelete="RESTRICT",
            name=op.f("fk_playback_completion_event_watch_event_id_watch_event"),
        ),
    )
    op.execute(_REFUSE_MUTATION)
    for table in (_RECEIPT, _MEMBERSHIP):
        op.execute(
            f"CREATE TRIGGER {table}_no_mutation BEFORE UPDATE OR DELETE ON {table}"
            " FOR EACH ROW EXECUTE FUNCTION playback_completion_reject_mutation()"
        )


def downgrade() -> None:
    for table in (_MEMBERSHIP, _RECEIPT):
        op.execute(f"DROP TRIGGER {table}_no_mutation ON {table}")
    op.execute("DROP FUNCTION playback_completion_reject_mutation()")
    op.drop_table(_MEMBERSHIP)
    for column in ("source_entry_id", "category_id"):
        op.drop_index(f"ix_{_RECEIPT}_{column}", table_name=_RECEIPT)
    op.drop_table(_RECEIPT)
