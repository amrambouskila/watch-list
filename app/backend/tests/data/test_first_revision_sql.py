"""What revision 0001 emits, proven without a database: `alembic upgrade base:0001 --sql` is the subject.

These are the tests that still run on a workstation with no Postgres on it. They are not a substitute for
`alembic check` - they are what makes a missing database an inconvenience rather than a blind spot.

The range is the FIRST revision alone, and that is the whole point of the file: every ordering claim below
- types before tables, views after them, children dropped before parents - is a claim about one
revision's own statements, and rendering the chain would turn each of them into a claim about how two
revisions interleave, which is not a thing this schema promises. What the chain as a whole must satisfy
is parity with the models, and the two tests at the foot of this file render `base:head` for exactly that.
Revision 0002's own shape is `tests/data/test_migration_0002.py`.
"""

from __future__ import annotations

import io
import re
from collections.abc import Callable
from functools import lru_cache
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_mock_engine
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import ExecutableDDLElement

from database_support import PHASE_ONE_TABLES, alembic_config, preserving_root_logging
from tv_watchlist.data.base import Base
from tv_watchlist.data.models import ALL_MODELS

# Offline mode only needs a dialect to compile against; nothing connects and nothing lives at this address.
OFFLINE_URL: Final[str] = "postgresql+asyncpg://tv:tv@127.0.0.1:5599/tv_offline"
# Alembic's own bookkeeping table, which the models neither declare nor own.
VERSION_TABLE: Final[str] = "alembic_version"
VIEWS: Final[tuple[str, str]] = ("episode_watch_state", "curated_entry_watch_state")
# `ALTER TABLE <t> ADD [COLUMN] <clause>;` - how a later revision adds to a table the first one built.
# Folded into that table's clause set so the chain can be compared with the models as one schema.
ALTER_PATTERN: Final[re.Pattern[str]] = re.compile(r"^ALTER TABLE (\w+) ADD (?:COLUMN )?(.+);$", re.MULTILINE)

TABLE_PATTERN: Final[re.Pattern[str]] = re.compile(r"^CREATE TABLE (\w+) \(\n(.*?)\n\)", re.DOTALL | re.MULTILINE)
INDEX_PATTERN: Final[re.Pattern[str]] = re.compile(r"^CREATE (?:UNIQUE )?INDEX [^\n;]+", re.MULTILINE)
TYPE_PATTERN: Final[re.Pattern[str]] = re.compile(r"^CREATE TYPE (\w+) AS ENUM \(([^)]*)\)", re.MULTILINE)
DISTINCT_ON_PATTERN: Final[re.Pattern[str]] = re.compile(r"DISTINCT ON \(([^)]+)\)")

# CLAUDE.md section 11.2 rule 12: occurred_at is client-supplied and can arrive late, recorded_at is
# server-assigned, and id is the last deterministic tie-break. Drop either of the last two and two
# identically stamped events make the derived status non-deterministic across replans.
TIE_BREAK: Final[str] = ", e.occurred_at DESC, e.recorded_at DESC, e.id DESC"
# The three latest-per-subject picks the two views make, and the view each one belongs to.
DISTINCT_ON_SUBJECTS: Final[tuple[tuple[str, str], ...]] = (
    ("episode_watch_state", "e.episode_id"),
    ("curated_entry_watch_state", "e.curated_entry_id"),
    ("curated_entry_watch_state", "e.title_id"),
)


def _normalised(sql: str) -> str:
    """Drop the trailing space SQLAlchemy leaves after each comma, so a clause splits on a clean newline."""
    return "\n".join(line.rstrip() for line in sql.splitlines())


def _render(run: Callable[[Config], None]) -> str:
    buffer = io.StringIO()
    config = alembic_config(OFFLINE_URL, output_buffer=buffer)
    with preserving_root_logging():
        run(config)
    return _normalised(buffer.getvalue())


@lru_cache(maxsize=1)
def first_revision() -> str:
    """The id of the revision with no parent, read off the chain rather than written down (R62)."""
    return ScriptDirectory.from_config(alembic_config(OFFLINE_URL)).get_base()


@lru_cache(maxsize=1)
def upgrade_sql() -> str:
    """The FIRST revision alone, which is what every ordering claim in this file is about."""
    return _render(lambda config: command.upgrade(config, f"base:{first_revision()}", sql=True))


@lru_cache(maxsize=1)
def downgrade_sql() -> str:
    # Offline mode cannot read the current revision out of a database, so the range is spelled out.
    return _render(lambda config: command.downgrade(config, f"{first_revision()}:base", sql=True))


@lru_cache(maxsize=1)
def head_sql() -> str:
    """Every revision there is. Only the two parity tests use it - the chain IS the schema to compare."""
    return _render(lambda config: command.upgrade(config, "base:head", sql=True))


@lru_cache(maxsize=1)
def metadata_sql() -> str:
    """The same DDL compiler, driven from `Base.metadata` instead of from the revision."""
    statements: list[str] = []
    dialect = postgresql.dialect()

    def collect(element: ExecutableDDLElement, *args: object, **kwargs: object) -> None:
        statements.append(str(element.compile(dialect=dialect)).strip())

    Base.metadata.create_all(create_mock_engine(OFFLINE_URL, collect), checkfirst=False)
    return _normalised(";\n\n".join(statements))


def _table_positions(sql: str) -> dict[str, int]:
    """Where each project table's CREATE lands. Alembic emits its own alembic_version table first, ahead of
    anything the revision does, so it is never the table an ordering claim is about."""
    return {match.group(1): match.start() for match in TABLE_PATTERN.finditer(sql) if match.group(1) != VERSION_TABLE}


def _table_clauses(sql: str) -> dict[str, frozenset[str]]:
    """{table: its column and constraint clauses as a set}, so a difference is content, never ordering.

    An `ALTER TABLE ... ADD` from a later revision is folded into the table it names, because the models
    render that same column and constraint inside the CREATE. Without the fold, every column a later
    revision adds would read as drift between the chain and the models.
    """
    clauses = {
        match.group(1): set(clause.strip() for clause in match.group(2).split(",\n") if clause.strip())
        for match in TABLE_PATTERN.finditer(sql)
        if match.group(1) != VERSION_TABLE
    }
    for match in ALTER_PATTERN.finditer(sql):
        if match.group(1) in clauses:
            clauses[match.group(1)].add(match.group(2).strip())
    return {table: frozenset(found) for table, found in clauses.items()}


def _index_statements(sql: str) -> set[str]:
    return {" ".join(match.group(0).split()) for match in INDEX_PATTERN.finditer(sql)}


def _view_body(sql: str, view: str) -> str:
    """Everything between `CREATE VIEW <view> AS` and the semicolon that ends the statement."""
    start = sql.index(f"CREATE VIEW {view} AS")
    return sql[start : sql.index(";", start)]


def _foreign_key_edges() -> set[tuple[str, str]]:
    """(child, parent) for every foreign key WITHIN the first revision - the real graph, not a list.

    Scoped to that revision's own tables because an edge whose other end a later revision created is not
    a claim about this one's CREATE or DROP order at all: it is added and removed by `ALTER TABLE`, in
    the revision that owns it, and `tests/data/test_migration_0002.py` is where that ordering is proven.
    """
    return {
        (table.name, constraint.referred_table.name)
        for table in Base.metadata.sorted_tables
        for constraint in table.foreign_key_constraints
        if constraint.referred_table.name != table.name
        and {table.name, constraint.referred_table.name} <= PHASE_ONE_TABLES
    }


def _enum_labels(sql: str) -> dict[str, tuple[str, ...]]:
    return {
        match.group(1): tuple(label.strip().strip("'") for label in match.group(2).split(","))
        for match in TYPE_PATTERN.finditer(sql)
    }


def test_the_revision_creates_the_eleven_phase_1_tables() -> None:
    created = _table_clauses(upgrade_sql())
    assert len(created) == 11
    assert set(created) == PHASE_ONE_TABLES
    assert PHASE_ONE_TABLES <= {model.__tablename__ for model in ALL_MODELS}


def test_the_revision_creates_the_ten_enum_types() -> None:
    labels = _enum_labels(upgrade_sql())
    assert len(labels) == 10
    assert set(labels) == {
        "media_type",
        "unit_kind",
        "resolution_state",
        "entity_kind",
        "external_source",
        "artwork_kind",
        "watch_event_kind",
        "watch_event_source",
        "watch_subject_kind",
        "sync_resource_type",
    }


def test_watch_event_source_carries_exactly_the_three_phase_1_labels() -> None:
    """A Jellyfin label would be a Phase 3 decision arriving in a Phase 1 revision."""
    assert _enum_labels(upgrade_sql())["watch_event_source"] == ("ui", "excel_mirror", "player")
    assert "jellyfin" not in upgrade_sql().lower()


def test_the_extension_is_created_before_the_table_whose_index_needs_it() -> None:
    sql = upgrade_sql()
    assert sql.index("CREATE EXTENSION IF NOT EXISTS pg_trgm") < sql.index("CREATE TABLE title")


def test_every_type_is_created_before_the_first_table_that_could_use_one() -> None:
    sql = upgrade_sql()
    first_table = min(_table_positions(sql).values())
    assert all(match.start() < first_table for match in TYPE_PATTERN.finditer(sql))


def test_the_append_only_trigger_lands_after_the_table_it_guards() -> None:
    sql = upgrade_sql()
    assert sql.index("CREATE OR REPLACE FUNCTION watch_event_reject_mutation") < sql.index(
        "CREATE TRIGGER watch_event_no_mutation"
    )
    assert sql.index("CREATE TABLE watch_event") < sql.index("CREATE TRIGGER watch_event_no_mutation")


@pytest.mark.parametrize("view", VIEWS)
def test_each_view_is_created_after_every_table_it_reads(view: str) -> None:
    sql = upgrade_sql()
    created_at = sql.index(f"CREATE VIEW {view}")
    assert max(_table_positions(sql).values()) < created_at


def test_the_entry_view_reads_the_episode_view_and_so_is_created_second() -> None:
    sql = upgrade_sql()
    assert sql.index("CREATE VIEW episode_watch_state") < sql.index("CREATE VIEW curated_entry_watch_state")


def test_a_title_may_exist_with_no_tmdb_id() -> None:
    """R2: a hand-entered local title with no provider match is a record, not an error."""
    clauses = _table_clauses(upgrade_sql())["title"]
    assert "tmdb_id INTEGER" in clauses


@pytest.mark.parametrize(("view", "subject"), DISTINCT_ON_SUBJECTS)
def test_each_latest_per_subject_pick_carries_the_full_three_key_tie_break(view: str, subject: str) -> None:
    assert f"ORDER BY {subject}{TIE_BREAK}" in _view_body(upgrade_sql(), view)


def test_no_fourth_distinct_on_slips_in_without_a_tie_break() -> None:
    """Named separately from the parametrised case above: that one proves the three we know about are
    correct, this one proves nobody added a fourth that is not."""
    sql = upgrade_sql()
    assert [match.group(1) for match in DISTINCT_ON_PATTERN.finditer(sql)] == [
        subject for _, subject in DISTINCT_ON_SUBJECTS
    ]


def test_the_tables_are_created_parent_before_child() -> None:
    created_at = _table_positions(upgrade_sql())
    for child, parent in _foreign_key_edges():
        assert created_at[parent] < created_at[child], f"{child} is created before {parent}"


def test_the_tables_are_dropped_child_before_parent() -> None:
    """Reverse dependency order, read off the models' own foreign keys rather than a hand-written list.

    Deliberately not an equality check against `reversed(Base.metadata.sorted_tables)`: SQLAlchemy's
    tie-break within one dependency tier is not a contract, so pinning it would go red for a non-bug.
    """
    sql = downgrade_sql()
    # Terminated with the semicolon, or `DROP TABLE curated_entry` matches inside `curated_entry_item`.
    dropped_at = {table: sql.index(f"DROP TABLE {table};") for table in PHASE_ONE_TABLES}
    assert len(dropped_at) == 11
    for child, parent in _foreign_key_edges():
        assert dropped_at[child] < dropped_at[parent], f"{child} is dropped after {parent}"


def test_the_downgrade_drops_the_views_then_the_tables_then_the_types() -> None:
    sql = downgrade_sql()
    # Terminated with the semicolon, or `DROP TABLE curated_entry` matches inside `curated_entry_item`.
    views = [sql.index(f"DROP VIEW IF EXISTS {view};") for view in VIEWS]
    tables = [sql.index(f"DROP TABLE {table};") for table in PHASE_ONE_TABLES]
    types = [sql.index(f"DROP TYPE {name};") for name in _enum_labels(upgrade_sql())]
    assert len(tables) == 11
    assert max(views) < min(tables)
    assert max(tables) < min(types)


def test_the_downgrade_drops_the_trigger_and_its_function_before_the_table() -> None:
    sql = downgrade_sql()
    assert sql.index("DROP TRIGGER IF EXISTS watch_event_no_mutation") < sql.index("DROP TABLE watch_event")
    assert sql.index("DROP FUNCTION IF EXISTS watch_event_reject_mutation") < sql.index("DROP TABLE watch_event")


def test_the_downgrade_leaves_the_extension_alone() -> None:
    """pg_trgm may be serving something else in the same database; creating it is not owning it."""
    assert "DROP EXTENSION" not in downgrade_sql()


def test_every_revision_together_and_the_models_describe_the_same_tables() -> None:
    """The offline stand-in for `alembic check`, which needs a database this machine may not have.

    The whole chain, not the first revision: the models are the schema as it stands after every revision,
    so this is the one claim in the file that would be wrong to narrow.
    """
    assert _table_clauses(head_sql()) == _table_clauses(metadata_sql())


def test_every_revision_together_and_the_models_describe_the_same_indexes() -> None:
    assert _index_statements(head_sql()) == _index_statements(metadata_sql())
