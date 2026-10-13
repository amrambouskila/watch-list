from __future__ import annotations

from typing import Final

import pytest
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    Index,
    Integer,
    Interval,
    Numeric,
    String,
    Table,
    UniqueConstraint,
    inspect,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB

from database_support import PHASE_ONE_TABLES
from tv_watchlist.data.base import Base
from tv_watchlist.data.enums import ResolutionState, UnitKind
from tv_watchlist.data.models import ALL_MODELS, Season, Title

# The whole schema as it stands: Phase 1's eleven, plus what every later revision has added.
EXPECTED_TABLES: Final[frozenset[str]] = PHASE_ONE_TABLES | {
    "jellyfin_item",
    "media_import",
    "media_import_operation",
    "playback_completion",
    "playback_completion_event",
}
DEFERRED_UNIQUES: Final[dict[str, tuple[str, ...]]] = {
    "curated_entry": ("category_id", "position"),
    "curated_entry_item": ("category_id", "absolute_position"),
    "episode_order": ("title_id", "order_type", "label", "sequence"),
}
# title 1, curated_entry 2, episode_order 1, external_id 2, artwork 3, watch_event 3, sync_state 2,
# jellyfin_item 1, media_import 3, media_import_operation 2.
ENUM_COLUMN_COUNT: Final[int] = 20


def _table(name: str) -> Table:
    return Base.metadata.tables[name]


def _checks(name: str) -> dict[str, str]:
    return {str(c.name): str(c.sqltext) for c in _table(name).constraints if isinstance(c, CheckConstraint)}


def _uniques(name: str) -> set[tuple[str, ...]]:
    return {
        tuple(column.name for column in constraint.columns)
        for constraint in _table(name).constraints
        if isinstance(constraint, UniqueConstraint)
    }


def _index(table: str, name: str) -> Index:
    return next(index for index in _table(table).indexes if index.name == name)


def _ondelete(table: str, column: str) -> str | None:
    return next(iter(_table(table).c[column].foreign_keys)).ondelete


def test_every_table_is_registered_and_nothing_else() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES
    assert {model.__tablename__ for model in ALL_MODELS} == EXPECTED_TABLES


def test_every_relationship_raises_instead_of_lazy_loading() -> None:
    for mapper in Base.registry.mappers:
        for relationship in mapper.relationships:
            assert relationship.lazy == "raise_on_sql", f"{mapper.class_.__name__}.{relationship.key}"


@pytest.mark.parametrize(
    ("model", "key"), [(Title, "seasons"), (Season, "episodes")], ids=["title.seasons", "season.episodes"]
)
def test_the_cascading_collections_delete_passively(model: type[Base], key: str) -> None:
    # delete-orphan would otherwise load the collection to cascade in Python - the one thing raise_on_sql
    # forbids - so the database's ON DELETE CASCADE has to be the thing that does the deleting.
    assert inspect(model).relationships[key].passive_deletes is True


def test_every_duration_is_integer_seconds_and_nothing_is_an_interval() -> None:
    for table in Base.metadata.tables.values():
        for column in table.columns:
            assert not isinstance(column.type, Interval), f"{table.name}.{column.name}"
            if column.name.endswith("_seconds"):
                assert isinstance(column.type, Integer), f"{table.name}.{column.name}"
                assert any(
                    column.name in str(constraint.sqltext)
                    for constraint in table.constraints
                    if hasattr(constraint, "sqltext")
                ), f"{table.name}.{column.name} has no CHECK"


def test_every_timestamp_is_timezone_aware() -> None:
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, DateTime):
                assert column.type.timezone, f"{table.name}.{column.name}"


def test_every_enum_column_uses_member_values_as_labels() -> None:
    seen = 0
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, ENUM):
                seen += 1
                assert column.type.create_type is False
                assert list(column.type.enums) == [member.value for member in column.type.enum_class]
    assert seen == ENUM_COLUMN_COUNT


@pytest.mark.parametrize(("table", "columns"), sorted(DEFERRED_UNIQUES.items()), ids=sorted(DEFERRED_UNIQUES))
def test_the_renumbering_uniques_are_deferrable(table: str, columns: tuple[str, ...]) -> None:
    match = [
        constraint
        for constraint in _table(table).constraints
        if hasattr(constraint, "columns") and tuple(c.name for c in constraint.columns) == columns
    ]
    assert match, f"{table} has no unique on {columns}"
    assert match[0].deferrable is True and match[0].initially == "DEFERRED"


def test_watch_event_is_append_only_in_shape() -> None:
    table = _table("watch_event")
    assert "updated_at" not in table.columns
    entry_fk = next(fk for fk in table.foreign_keys if fk.column.table.name == "curated_entry")
    category_fk = next(fk for fk in table.foreign_keys if fk.column.table.name == "category")
    assert entry_fk.ondelete == "RESTRICT" and category_fk.ondelete == "RESTRICT"


@pytest.mark.parametrize("name", ["playback_completion", "playback_completion_event"])
def test_completion_history_has_uuid_identity_without_mutable_timestamps(name: str) -> None:
    table = _table(name)
    assert [column.name for column in table.primary_key.columns] == ["id"]
    assert str(table.c.id.server_default.arg) == "gen_random_uuid()"
    assert {"created_at", "updated_at"}.isdisjoint(table.columns.keys())
    assert all(key.ondelete == "RESTRICT" for key in table.foreign_keys)


def test_receipt_references_only_retained_history_and_indexes_its_curated_context() -> None:
    table = _table("playback_completion")
    assert {(key.parent.name, key.target_fullname) for key in table.foreign_keys} == {
        ("selected_watch_event_id", "watch_event.id"),
        ("category_id", "category.id"),
        ("source_entry_id", "curated_entry.id"),
    }
    assert {index.name for index in table.indexes} == {
        "ix_playback_completion_category_id",
        "ix_playback_completion_source_entry_id",
    }
    assert _uniques(table.name) == {("selected_watch_event_id",)}
    assert set(_checks(table.name)) == {
        "ck_playback_completion_jellyfin_id_nonempty",
        "ck_playback_completion_queue_fingerprint_shape",
        "ck_playback_completion_occurrence_snapshot_array",
        "ck_playback_completion_indices_nonnegative",
        "ck_playback_completion_index_range",
        "ck_playback_completion_numbering_shape",
    }


def test_receipt_snapshot_types_and_nullability_match_the_contract() -> None:
    table = _table("playback_completion")
    assert isinstance(table.c.occurrence_snapshot.type, JSONB)
    assert {column.name: column.type.length for column in table.columns if isinstance(column.type, String)} == {
        "jellyfin_id_snapshot": 64,
        "order_type": 32,
        "order_label": 120,
        "queue_fingerprint": 64,
    }
    assert {column.name for column in table.columns if column.nullable} == {
        "order_type",
        "parent_index_number",
        "index_number",
        "index_number_end",
    }
    assert table.c.order_label.default.arg == table.c.order_label.server_default.arg == ""


def test_completion_membership_has_only_immutable_history_foreign_keys() -> None:
    table = _table("playback_completion_event")
    assert {(key.parent.name, key.target_fullname) for key in table.foreign_keys} == {
        ("completion_id", "playback_completion.id"),
        ("watch_event_id", "watch_event.id"),
    }
    assert not any(column.nullable for column in table.columns)


def test_watch_event_names_exactly_one_subject() -> None:
    assert _checks("watch_event")["ck_watch_event_one_subject"] == (
        "num_nonnulls(episode_id, title_id, curated_entry_id) = 1"
    )


@pytest.mark.parametrize(
    ("member", "column"),
    [("episode", "episode_id"), ("title", "title_id"), ("curated_entry", "curated_entry_id")],
)
def test_watch_event_ties_its_subject_kind_to_the_populated_column(member: str, column: str) -> None:
    assert (
        f"subject_kind = '{member}' AND {column} IS NOT NULL"
        in _checks("watch_event")["ck_watch_event_kind_matches_column"]
    )


@pytest.mark.parametrize(
    ("member", "column"), [("title", "title_id"), ("season", "season_id"), ("episode", "episode_id")]
)
def test_artwork_ties_its_entity_kind_to_the_populated_column(member: str, column: str) -> None:
    assert f"entity_kind = '{member}' AND {column} IS NOT NULL" in _checks("artwork")["ck_artwork_kind_matches_column"]


@pytest.mark.parametrize(
    ("column", "rule"),
    [
        ("episode_id", "SET NULL"),
        ("title_id", "SET NULL"),
        ("curated_entry_id", "RESTRICT"),
        ("category_id", "RESTRICT"),
    ],
)
def test_watch_event_holds_the_curated_chain_and_lets_metadata_go(column: str, rule: str) -> None:
    assert _ondelete("watch_event", column) == rule


def test_the_curated_chain_restricts_and_metadata_cascades() -> None:
    entry_to_category = next(fk for fk in _table("curated_entry").foreign_keys if fk.column.table.name == "category")
    season_to_title = next(fk for fk in _table("season").foreign_keys if fk.column.table.name == "title")
    episode_to_season = next(fk for fk in _table("episode").foreign_keys if fk.column.table.name == "season")
    assert entry_to_category.ondelete == "RESTRICT"
    assert season_to_title.ondelete == "CASCADE"
    assert episode_to_season.ondelete == "CASCADE"


def test_the_queue_holds_exactly_one_playable_unit_per_row() -> None:
    checks = [str(c.sqltext) for c in _table("curated_entry_item").constraints if hasattr(c, "sqltext")]
    assert any("num_nonnulls(episode_id, movie_title_id) = 1" in check for check in checks)


def test_order_type_is_an_open_string_column() -> None:
    assert isinstance(_table("episode_order").c.order_type.type, String)
    assert isinstance(_table("curated_entry").c.order_type.type, String)


def test_artwork_has_three_partial_primary_indexes() -> None:
    # dialect_options["postgresql"] is keyed WITHOUT the prefix - `where`, `using`, `ops`. The prefixed
    # spelling lives in index.dialect_kwargs, so `"postgresql_where" in index.dialect_options[...]` is
    # False for every index and would make this assertion vacuous.
    partial = [
        index
        for index in _table("artwork").indexes
        if index.unique and index.dialect_options["postgresql"]["where"] is not None
    ]
    assert {index.name for index in partial} == {
        "ix_artwork_primary_title",
        "ix_artwork_primary_season",
        "ix_artwork_primary_episode",
    }


def test_the_tmdb_join_key_is_unique_per_media_type() -> None:
    assert ("media_type", "tmdb_id") in _uniques("title")


def test_a_manually_entered_title_needs_no_provider_id() -> None:
    # Risk register R2. Postgres treats NULLs as distinct, so the unique above survives untouched.
    assert _table("title").c.tmdb_id.nullable is True


def test_a_raw_insert_gets_the_defaults_the_orm_would_have_applied() -> None:
    table = _table("curated_entry")
    assert table.c.unit_kind.server_default.arg == UnitKind.UNKNOWN.value
    assert table.c.resolution_state.server_default.arg == ResolutionState.UNRESOLVED.value


def test_the_verbatim_row_and_the_workbook_mtime_keep_their_wire_types() -> None:
    assert isinstance(_table("curated_entry").c.raw_cells.type, JSONB)
    # The same st_mtime float CategorySummary.mtime already carries end to end.
    assert isinstance(_table("category").c.workbook_mtime.type, Float)


def test_resolution_confidence_is_a_bounded_two_place_decimal() -> None:
    column = _table("curated_entry").c.resolution_confidence
    assert isinstance(column.type, Numeric)
    assert (column.type.precision, column.type.scale) == (3, 2)
    assert "resolution_confidence" in _checks("curated_entry")["ck_curated_entry_confidence_unit_interval"]


def test_the_review_queue_has_its_partial_index() -> None:
    where = _index("curated_entry", "ix_curated_entry_needs_review").dialect_options["postgresql"]["where"]
    assert str(where) == "removed_at IS NULL AND resolution_state IN ('unresolved', 'auto')"


def test_the_fuzzy_title_fallback_is_a_trigram_gin_index() -> None:
    options = _index("title", "ix_title_name_trgm").dialect_options["postgresql"]
    assert options["using"] == "gin"
    assert options["ops"] == {"name": "gin_trgm_ops"}


def test_episode_and_sync_state_keep_their_uniques() -> None:
    assert _uniques("episode") == {("season_id", "episode_number"), ("tmdb_episode_id",)}
    assert ("source", "resource_type", "resource_key") in _uniques("sync_state")
    assert "ck_sync_state_failures_non_negative" in _checks("sync_state")
