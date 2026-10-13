from __future__ import annotations

from enum import StrEnum
from pathlib import Path

import pytest
from sqlalchemy.dialects.postgresql import ENUM

from tv_watchlist.data import enums
from tv_watchlist.data.base import Base
from tv_watchlist.data.enums import (
    ArtworkKind,
    Availability,
    EntityKind,
    ExternalSource,
    JellyfinItemKind,
    MediaImportIdentifiedBy,
    MediaImportSource,
    MediaImportStatus,
    MediaType,
    OrderType,
    ResolutionState,
    SyncResourceType,
    UnitKind,
    WatchEventKind,
    WatchEventSource,
    WatchSubjectKind,
    pg_enum,
)

EVERY_ENUM = (
    MediaType,
    OrderType,
    UnitKind,
    ResolutionState,
    EntityKind,
    ExternalSource,
    ArtworkKind,
    WatchEventKind,
    WatchEventSource,
    WatchSubjectKind,
    SyncResourceType,
    JellyfinItemKind,
    MediaImportSource,
    MediaImportIdentifiedBy,
    MediaImportStatus,
    Availability,
)


@pytest.mark.parametrize("members", EVERY_ENUM, ids=lambda members: members.__name__)
def test_every_vocabulary_is_a_str_enum_with_lowercase_values(members: type[StrEnum]) -> None:
    assert issubclass(members, StrEnum)
    for member in members:
        assert member.value == member.value.lower()
        assert " " not in member.value


def test_pg_enum_labels_are_member_values_not_names() -> None:
    column_type = pg_enum(WatchEventKind, "watch_event_kind")
    assert isinstance(column_type, ENUM)
    assert column_type.name == "watch_event_kind"
    assert list(column_type.enums) == ["started", "progressed", "completed", "skipped", "unset"]
    assert column_type.create_type is False


def test_the_five_watch_kinds_the_mirror_projects_exist() -> None:
    assert {kind.value for kind in WatchEventKind} == {"started", "progressed", "completed", "skipped", "unset"}


def test_watch_sources_name_the_player_not_the_server_that_streamed_the_file() -> None:
    """Playback comes from the browser's own <video> element, so the source is the player."""
    assert {source.value for source in WatchEventSource} == {"ui", "excel_mirror", "player"}


def test_order_type_is_not_a_closed_database_vocabulary() -> None:
    """The season-type list is read at runtime; the app names only the numberings it computes with."""
    assert {kind.value for kind in OrderType} == {"aired", "absolute", "dvd", "alternate"}
    assert not hasattr(enums, "ORDER_TYPE_PG_ENUM")


def test_availability_arrives_with_its_computing_service_without_stubbing_other_vocabularies() -> None:
    """A later phase's label arrives with the task that needs it, carrying its own enum-altering revision."""
    assert list(Availability) == [Availability.IN_LIBRARY, Availability.NOT_IN_LIBRARY, Availability.AMBIGUOUS]
    assert {source.value for source in ExternalSource} == {"tmdb", "tvdb", "imdb", "wikidata"}
    assert not {resource.value for resource in SyncResourceType} & {"jellyfin_library", "streaming_availability"}


def test_availability_is_not_a_postgres_enum() -> None:
    for table in Base.metadata.tables.values():
        for column in table.columns:
            assert getattr(column.type, "enum_class", None) is not Availability
            assert column.name != "availability"
    revisions = Path(__file__).resolve().parents[2] / "alembic" / "versions"
    assert all("Availability" not in path.read_text() for path in revisions.glob("*.py"))
