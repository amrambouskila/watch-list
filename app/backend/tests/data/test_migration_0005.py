from __future__ import annotations

import io

from alembic import command

from database_support import alembic_config, preserving_root_logging


def test_completion_revision_is_additive_and_its_teardown_is_dependency_ordered() -> None:
    up, down = io.StringIO(), io.StringIO()
    url = "postgresql+asyncpg://tv:tv@127.0.0.1:5599/tv_offline"
    with preserving_root_logging():
        command.upgrade(alembic_config(url, output_buffer=up), "0004:0005", sql=True)
        command.downgrade(alembic_config(url, output_buffer=down), "0005:0004", sql=True)
    sql = up.getvalue()
    assert sql.index("CREATE TABLE playback_completion (") < sql.index("CREATE TABLE playback_completion_event (")
    assert sql.count("CREATE TABLE") == 2
    assert sql.count("CREATE TRIGGER") == 2
    assert sql.count("ON DELETE RESTRICT") == 5
    assert sql.count(" UNIQUE (") == 3
    assert "CREATE TYPE" not in sql
    assert "ALTER TABLE watch_event" not in sql
    for table in ("playback_completion", "playback_completion_event"):
        assert sql.index("CREATE FUNCTION playback_completion_reject_mutation") < sql.index(
            f"CREATE TRIGGER {table}_no_mutation"
        )
        assert sql.index(f"CREATE TABLE {table} (") < sql.index(f"CREATE TRIGGER {table}_no_mutation")
    sql = down.getvalue()
    assert sql.index("DROP TRIGGER playback_completion_event_no_mutation") < sql.index(
        "DROP FUNCTION playback_completion_reject_mutation"
    )
    assert sql.index("DROP TRIGGER playback_completion_no_mutation") < sql.index(
        "DROP FUNCTION playback_completion_reject_mutation"
    )
    assert sql.index("DROP TABLE playback_completion_event") < sql.index("DROP TABLE playback_completion;")
    assert "DROP TABLE watch_event" not in sql
    assert "DROP TYPE" not in sql
