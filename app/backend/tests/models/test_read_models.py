"""The Phase 1 read contracts: frozen, from_attributes, the `cells` alias, and the TypeScript mirrors.

Offline by design - these are the contract itself, not the query that fills it, so nothing here needs a
database. The Postgres side of T28 lives in tests/services/test_entries_service.py and tests/api/test_entries.py.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Final, get_args

import pytest
from pydantic import BaseModel, ValidationError

from ts_types import TS_OPTIONAL_KEY, ts_fields, ts_source
from tv_watchlist.data.enums import Availability, MediaType, ResolutionState, UnitKind, WatchEventKind
from tv_watchlist.models.column_spec import ColumnRole, ColumnSpec
from tv_watchlist.models.curated_entry_read import CuratedEntryRead
from tv_watchlist.models.entry_progress import EntryProgress
from tv_watchlist.models.episode_read import EpisodeRead
from tv_watchlist.models.library_sync_result import LibrarySyncResult
from tv_watchlist.models.title_read import TitleRead

# The shared reader matches an optional key too, because a request body has them. A response does not:
# under `exactOptionalPropertyTypes` an optional key means "may be absent", which is not what a field
# the backend always serialises is. The assertion below is what holds these three to that, and it is
# why it reads the source rather than the field list - the failure then names the real problem.

# Computed at read time, on both category pages and every review response.
PHASE_THREE_FIELDS: Final[frozenset[str]] = frozenset({"availability", "jellyfin_item_id"})

RESPONSE_MODELS: Final[tuple[type[BaseModel], ...]] = (
    TitleRead,
    EpisodeRead,
    EntryProgress,
    CuratedEntryRead,
    LibrarySyncResult,
)

A_TITLE_ID: Final[uuid.UUID] = uuid.UUID("11111111-1111-4111-8111-111111111111")
AN_ENTRY_ID: Final[uuid.UUID] = uuid.UUID("22222222-2222-4222-8222-222222222222")
AN_EPISODE_ID: Final[uuid.UUID] = uuid.UUID("33333333-3333-4333-8333-333333333333")
ONE_PIECE_TMDB_ID: Final[int] = 37854
A_CELL_GRID: Final[dict[str, str]] = {"order": "1", "title": "One Piece", "watched": "Watched"}
# The workbook id `category.slug` carries, which R82 put on the wire beside the entry's own id.
A_CATEGORY_SLUG: Final[str] = "one-piece"
# One note carrying all three clauses an entry can accumulate: the resolver's own sentence, the
# expansion's `queue: ` clause and a reviewer's `review: ` one.
A_RESOLUTION_NOTE: Final[str] = "auto: 0.94 on title and year | queue: absolute covers 18 of 18 | review: confirm"


def _a_title_row() -> SimpleNamespace:
    """What an ORM `Title` looks like to `from_attributes`. `poster_url` is absent: it is served, not stored."""
    return SimpleNamespace(
        id=A_TITLE_ID,
        media_type=MediaType.TV,
        tmdb_id=ONE_PIECE_TMDB_ID,
        name="One Piece",
        original_name="ワンピース",
        first_air_date=date(1999, 10, 20),
        last_air_date=None,
        runtime_seconds=1440,
        episode_count=1100,
        season_count=23,
        status="Returning Series",
    )


def _an_entry_row() -> SimpleNamespace:
    """An ORM `CuratedEntry` plus the two things the service computes for it."""
    return SimpleNamespace(
        id=AN_ENTRY_ID,
        category_slug=A_CATEGORY_SLUG,
        position=1,
        sheet_row=2,
        unit_kind=UnitKind.EPISODES,
        order_type="absolute",
        order_label="",
        span_start=1,
        span_end=18,
        resolution_state=ResolutionState.CONFIRMED,
        resolution_confidence=0.94,
        resolution_note=A_RESOLUTION_NOTE,
        raw_title="One Piece",
        raw_unit="E1-18",
        raw_release="1999",
        raw_cells=A_CELL_GRID,
        title=TitleRead.model_validate(_a_title_row()),
        progress=EntryProgress(
            kind=WatchEventKind.PROGRESSED,
            episode_total=18,
            episode_completed=9,
            episode_skipped=0,
            episode_started=1,
        ),
        availability=Availability.NOT_IN_LIBRARY,
    )


@pytest.mark.parametrize("model", RESPONSE_MODELS, ids=lambda model: model.__name__)
def test_every_response_model_is_frozen_and_reads_from_attributes(model: type[BaseModel]) -> None:
    assert model.model_config["from_attributes"] is True
    assert model.model_config["frozen"] is True


def test_a_frozen_response_model_refuses_assignment() -> None:
    progress = EntryProgress(
        kind=WatchEventKind.UNSET, episode_total=0, episode_completed=0, episode_skipped=0, episode_started=0
    )
    with pytest.raises(ValidationError):
        progress.episode_total = 1  # type: ignore[misc]  # the refusal under test


def test_a_title_reads_off_an_orm_row_and_defaults_the_url_it_does_not_store() -> None:
    title = TitleRead.model_validate(_a_title_row())

    assert title.tmdb_id == ONE_PIECE_TMDB_ID
    assert title.media_type is MediaType.TV
    # The attribute is absent on the ORM class, so the default stands rather than the validation failing.
    assert title.poster_url is None


def test_a_title_with_no_provider_match_is_a_first_class_record() -> None:
    """`Title.tmdb_id` is nullable on purpose (CLAUDE.md section 5.13, risk register R2)."""
    row = _a_title_row()
    row.tmdb_id = None

    assert TitleRead.model_validate(row).tmdb_id is None


def test_an_episode_reads_off_an_orm_row() -> None:
    episode = EpisodeRead.model_validate(
        SimpleNamespace(
            id=AN_EPISODE_ID,
            title_id=A_TITLE_ID,
            season_number=1,
            episode_number=4,
            name="Luffy's Past",
            air_date=date(1999, 11, 10),
            runtime_seconds=1440,
        )
    )

    assert episode.season_number == 1
    assert episode.still_url is None


def test_progress_reads_off_the_view_row() -> None:
    progress = EntryProgress.model_validate(
        SimpleNamespace(
            kind="completed",
            episode_total=3,
            episode_completed=2,
            episode_skipped=1,
            episode_started=0,
            as_of=datetime(2026, 9, 20, 13, 0, tzinfo=UTC),
        )
    )

    assert progress.kind is WatchEventKind.COMPLETED
    assert progress.episode_completed == 2


def test_the_cells_field_is_fed_by_raw_cells_and_serialised_as_cells() -> None:
    entry = CuratedEntryRead.model_validate(_an_entry_row())

    assert entry.cells == A_CELL_GRID
    assert "cells" in entry.model_dump()
    assert "raw_cells" not in entry.model_dump()


def test_the_cells_alias_is_the_only_way_in() -> None:
    """The alias reads the ORM column; a payload keyed `cells` is not a curated entry."""
    row = _an_entry_row()
    del row.raw_cells

    with pytest.raises(ValidationError):
        CuratedEntryRead.model_validate(row)


def test_order_type_is_an_open_string_never_the_app_s_own_enum() -> None:
    """TheTVDB's season types are read at runtime, so a type this app has never seen must still serialise."""
    row = _an_entry_row()
    row.order_type = "alttwo"

    assert CuratedEntryRead.model_validate(row).order_type == "alttwo"
    assert CuratedEntryRead.model_fields["order_type"].annotation == (str | None)


def test_the_resolution_note_is_served_beside_the_confidence_it_explains() -> None:
    """Ruling 45: a row a human is asked to judge has to say what was already tried, and by whom.

    Its place in the field order is the contract too - it is read next to the confidence it explains, on
    both sides of the wire, and the mirror test below would not notice the two drifting apart.
    """
    entry = CuratedEntryRead.model_validate(_an_entry_row())

    assert entry.resolution_note == A_RESOLUTION_NOTE
    fields = list(CuratedEntryRead.model_fields)
    assert fields[fields.index("resolution_confidence") + 1] == "resolution_note"
    mirror = ts_fields("CuratedEntryRead")
    assert mirror[mirror.index("resolution_confidence") + 1] == "resolution_note"


def test_the_category_slug_sits_beside_the_entrys_own_id_on_both_sides() -> None:
    """R82: the queue spans every category, so the workbook a row belongs to travels with the row."""
    entry = CuratedEntryRead.model_validate(_an_entry_row())
    mirror = ts_fields("CuratedEntryRead")

    assert entry.category_slug == A_CATEGORY_SLUG
    assert list(CuratedEntryRead.model_fields)[:2] == ["id", "category_slug"]
    assert mirror[:2] == ["id", "category_slug"]


def test_a_row_with_nothing_recorded_serves_an_empty_note_never_a_null() -> None:
    """The column is `Text NOT NULL DEFAULT ''`, so the wire field is a string and never `None`."""
    row = _an_entry_row()
    row.resolution_note = ""

    assert CuratedEntryRead.model_validate(row).resolution_note == ""
    assert CuratedEntryRead.model_fields["resolution_note"].annotation is str


def test_the_phase_three_fields_report_a_state_and_a_nullable_title_level_id() -> None:
    entry = CuratedEntryRead.model_validate(_an_entry_row())
    assert PHASE_THREE_FIELDS <= CuratedEntryRead.model_fields.keys()
    assert entry.availability is Availability.NOT_IN_LIBRARY
    assert entry.jellyfin_item_id is None
    assert CuratedEntryRead.model_fields["availability"].is_required()


@pytest.mark.parametrize(
    ("model", "name"),
    [
        (TitleRead, "TitleRead"),
        (EntryProgress, "EntryProgress"),
        (CuratedEntryRead, "CuratedEntryRead"),
        (ColumnSpec, "ColumnSpec"),
        (LibrarySyncResult, "LibrarySyncResult"),
    ],
    ids=["TitleRead", "EntryProgress", "CuratedEntryRead", "ColumnSpec", "LibrarySyncResult"],
)
def test_the_typescript_mirror_carries_the_same_snake_case_fields_in_the_same_order(
    model: type[BaseModel], name: str
) -> None:
    # Every field is serialised, so every key is present: a nullable one is `T | null`, never optional.
    assert TS_OPTIONAL_KEY not in ts_source(name)
    assert ts_fields(name) == list(model.model_fields)


def test_the_typescript_column_role_is_exactly_the_python_literal_members_in_order() -> None:
    """`ColumnRole` is a `Literal`, not a `data/enums.py` `StrEnum` - `get_args` reads its members."""
    spelled = " | ".join(f'"{member}"' for member in get_args(ColumnRole))
    assert f"export type ColumnRole = {spelled};" in ts_source("ColumnSpec").splitlines()


@pytest.mark.parametrize(
    ("file_name", "declared"),
    [
        ("TitleRead", 'export type MediaType = "movie" | "tv";'),
        (
            "EntryProgress",
            'export type WatchEventKind = "started" | "progressed" | "completed" | "skipped" | "unset";',
        ),
        (
            "CuratedEntryRead",
            'export type UnitKind = "movie" | "episodes" | "season" | "series" | "special" | "unknown";',
        ),
        (
            "CuratedEntryRead",
            'export type ResolutionState = "unresolved" | "auto" | "confirmed" | "rejected";',
        ),
    ],
    ids=["MediaType", "WatchEventKind", "UnitKind", "ResolutionState"],
)
def test_the_typescript_mirror_spells_each_enum_the_way_postgres_labels_it(file_name: str, declared: str) -> None:
    assert declared in ts_source(file_name).splitlines()


@pytest.mark.parametrize(
    ("members", "declared"),
    [
        (MediaType, 'export type MediaType = "movie" | "tv";'),
        (
            WatchEventKind,
            'export type WatchEventKind = "started" | "progressed" | "completed" | "skipped" | "unset";',
        ),
        (UnitKind, 'export type UnitKind = "movie" | "episodes" | "season" | "series" | "special" | "unknown";'),
        (ResolutionState, 'export type ResolutionState = "unresolved" | "auto" | "confirmed" | "rejected";'),
    ],
    ids=["MediaType", "WatchEventKind", "UnitKind", "ResolutionState"],
)
def test_each_declared_union_is_exactly_the_python_vocabulary(members: type, declared: str) -> None:
    """The union above is the contract only while it still names every member, in order."""
    name = members.__name__
    spelled = " | ".join(f'"{member.value}"' for member in members)
    assert declared == f"export type {name} = {spelled};"
