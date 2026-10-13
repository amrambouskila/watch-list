from __future__ import annotations

import io

from alembic import command

from database_support import alembic_config, preserving_root_logging


def test_operation_revision_creates_and_drops_only_its_own_type_and_table() -> None:
    up, down = io.StringIO(), io.StringIO()
    url = "postgresql+asyncpg://tv:tv@127.0.0.1:5599/tv_offline"
    with preserving_root_logging():
        command.upgrade(alembic_config(url, output_buffer=up), "0003:0004", sql=True)
        command.downgrade(alembic_config(url, output_buffer=down), "0004:0003", sql=True)
    sql = up.getvalue()
    assert sql.index("CREATE TYPE media_import_operation_phase") < sql.index("CREATE TABLE media_import_operation")
    assert sql.count("CREATE UNIQUE INDEX ix_media_import_operation_active_") == 3
    assert "ON DELETE RESTRICT" in sql
    assert "CREATE TYPE media_import_status" not in sql
    sql = down.getvalue()
    assert sql.index("DROP TABLE media_import_operation") < sql.index("DROP TYPE media_import_operation_phase")
    assert "DROP TYPE media_import_status" not in sql
