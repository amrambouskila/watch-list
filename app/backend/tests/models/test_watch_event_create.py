"""The watch-log contracts: the request body's refusals and the response shape.

Offline by design - these are the boundary itself, not the query behind it. The database `CHECK`
constraints say the same things a second time, on purpose (CLAUDE.md section 5.15): one refuses a bad
request with a 422 at the edge, the other guarantees the invariant for every writer, including a data
migration that never passes through this model. The Postgres side of T29 is in
tests/services/test_watch_events_service.py and tests/api/test_watch_events.py.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, Final

import pytest
from pydantic import BaseModel, ValidationError

from ts_types import TS_OPTIONAL_KEY, ts_fields, ts_source
from tv_watchlist.constants import MAX_DEVICE_LENGTH, MAX_NOTE_LENGTH
from tv_watchlist.data.enums import WatchEventKind, WatchEventSource, WatchSubjectKind
from tv_watchlist.models.entry_progress import EntryProgress
from tv_watchlist.models.watch_event_create import WatchEventCreate
from tv_watchlist.models.watch_event_read import WatchEventRead

AN_EPISODE_ID: Final[uuid.UUID] = uuid.UUID("33333333-3333-4333-8333-333333333333")
AN_ENTRY_ID: Final[uuid.UUID] = uuid.UUID("22222222-2222-4222-8222-222222222222")
A_CATEGORY_ID: Final[uuid.UUID] = uuid.UUID("44444444-4444-4444-8444-444444444444")
AN_EVENT_ID: Final[uuid.UUID] = uuid.UUID("55555555-5555-4555-8555-555555555555")
OCCURRED_AT: Final[datetime] = datetime(2026, 9, 20, 13, 0, tzinfo=UTC)
RECORDED_AT: Final[datetime] = datetime(2026, 9, 20, 13, 0, 4, tzinfo=UTC)
A_LABOON_KEY: Final[str] = "tv:37854:s2:e62"


def _body(**overrides: Any) -> dict[str, Any]:  # noqa: ANN401  # a request payload is heterogeneous by nature
    """A well-formed body, as JSON would carry it."""
    payload: dict[str, Any] = {
        "subject_kind": "episode",
        "subject_id": str(AN_EPISODE_ID),
        "kind": "completed",
    }
    payload.update(overrides)
    return payload


def _stored_event(**overrides: Any) -> SimpleNamespace:  # noqa: ANN401  # mirrors an ORM row's columns
    row = SimpleNamespace(
        id=AN_EVENT_ID,
        occurred_at=OCCURRED_AT,
        recorded_at=RECORDED_AT,
        subject_kind=WatchSubjectKind.EPISODE,
        kind=WatchEventKind.COMPLETED,
        source=WatchEventSource.UI,
        tmdb_key=A_LABOON_KEY,
        curated_entry_id=AN_ENTRY_ID,
        category_id=A_CATEGORY_ID,
        position_seconds=None,
        runtime_seconds=None,
        progress=None,
    )
    for name, value in overrides.items():
        setattr(row, name, value)
    return row


# -- the request body --------------------------------------------------------------------------------


def test_a_well_formed_body_carries_the_subject_as_one_typed_pair() -> None:
    """`(subject_kind, subject_id)` is one discriminated pair at the edge; the service maps it onto the
    typed FK column, which is where the `one_subject` CHECK can hold it."""
    body = WatchEventCreate.model_validate(_body())

    assert body.subject_kind is WatchSubjectKind.EPISODE
    assert body.subject_id == AN_EPISODE_ID
    assert body.kind is WatchEventKind.COMPLETED
    assert body.category_id is None
    assert body.occurred_at is None


def test_a_progressed_event_without_position_is_refused_at_the_boundary() -> None:
    """The DB CHECK `progressed_has_position` (T10) is the second line of defence, not the first."""
    with pytest.raises(ValidationError, match="a progressed event needs position_seconds"):
        WatchEventCreate.model_validate(_body(kind="progressed"))


def test_a_progressed_event_with_a_position_is_accepted() -> None:
    body = WatchEventCreate.model_validate(_body(kind="progressed", position_seconds=42))

    assert body.position_seconds == 42


@pytest.mark.parametrize(
    "kind",
    [kind.value for kind in WatchEventKind if kind is not WatchEventKind.PROGRESSED],
    ids=[kind.value for kind in WatchEventKind if kind is not WatchEventKind.PROGRESSED],
)
def test_every_other_kind_needs_no_position(kind: str) -> None:
    assert WatchEventCreate.model_validate(_body(kind=kind)).position_seconds is None


def test_extra_fields_are_forbidden() -> None:
    """`source` is the server's to set: `ui` here, `player` from the Phase 3 player, never the body's."""
    with pytest.raises(ValidationError):
        WatchEventCreate.model_validate(_body(source="ui"))


def test_the_tmdb_key_cannot_be_supplied_by_the_body() -> None:
    """The log's own identity is derived server-side or not at all (CLAUDE.md section 5.13)."""
    with pytest.raises(ValidationError):
        WatchEventCreate.model_validate(_body(tmdb_key=A_LABOON_KEY))

    assert "tmdb_key" not in WatchEventCreate.model_fields


def test_a_float_position_is_refused_not_rounded() -> None:
    """Integer seconds cross the boundary: the browser rounds `currentTime` once, in the player."""
    with pytest.raises(ValidationError):
        WatchEventCreate.model_validate(_body(kind="progressed", position_seconds=12.5))

    assert WatchEventCreate.model_validate(_body(kind="progressed", position_seconds=12)).position_seconds == 12


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("position_seconds", -1),
        ("runtime_seconds", 0),
        ("runtime_seconds", -1),
        ("device", "d" * (MAX_DEVICE_LENGTH + 1)),
        ("note", "n" * (MAX_NOTE_LENGTH + 1)),
        ("subject_id", "not-a-uuid"),
        ("subject_kind", "sheet_row"),
        ("kind", "watched"),
    ],
    ids=[
        "negative-position",
        "zero-runtime",
        "negative-runtime",
        "device-too-long",
        "note-too-long",
        "subject-not-a-uuid",
        "unknown-subject-kind",
        "unknown-kind",
    ],
)
def test_the_bounds_are_refused_at_the_boundary(field: str, value: object) -> None:
    # The override lands last, so a case narrowing one of the well-formed keys really does narrow it.
    overrides: dict[str, object] = {"kind": "progressed", "position_seconds": 1}
    overrides[field] = value

    with pytest.raises(ValidationError):
        WatchEventCreate.model_validate(_body(**overrides))


@pytest.mark.parametrize(
    ("field", "value"),
    [("device", "d" * MAX_DEVICE_LENGTH), ("note", "n" * MAX_NOTE_LENGTH), ("position_seconds", 0)],
    ids=["device-at-the-cap", "note-at-the-cap", "zero-position"],
)
def test_the_caps_themselves_are_accepted(field: str, value: object) -> None:
    assert getattr(WatchEventCreate.model_validate(_body(**{field: value})), field) == value


def test_a_late_client_stamp_is_carried_as_given() -> None:
    """A Jellyfin or player report may arrive an hour after the thing it describes (section 11.2, rule 12)."""
    body = WatchEventCreate.model_validate(_body(occurred_at=OCCURRED_AT.isoformat()))

    assert body.occurred_at == OCCURRED_AT


# -- the response ------------------------------------------------------------------------------------


@pytest.mark.parametrize("model", [WatchEventRead], ids=["WatchEventRead"])
def test_the_response_model_is_frozen_and_reads_from_attributes(model: type[BaseModel]) -> None:
    assert model.model_config["from_attributes"] is True
    assert model.model_config["frozen"] is True


def test_the_request_model_forbids_extras_rather_than_freezing() -> None:
    assert WatchEventCreate.model_config["extra"] == "forbid"


def test_the_response_reads_off_a_stored_row() -> None:
    read = WatchEventRead.model_validate(_stored_event())

    assert read.id == AN_EVENT_ID
    assert read.recorded_at == RECORDED_AT
    assert read.source is WatchEventSource.UI
    assert read.tmdb_key == A_LABOON_KEY
    assert read.progress is None


def test_the_response_carries_the_entrys_derived_progress() -> None:
    """The UI repaints from the view, not from the request it just sent."""
    progress = EntryProgress(
        kind=WatchEventKind.PROGRESSED, episode_total=18, episode_completed=9, episode_skipped=0, episode_started=1
    )

    read = WatchEventRead.model_validate(_stored_event(progress=progress))

    assert read.progress == progress


def test_an_event_no_curated_row_covers_still_reads_back() -> None:
    """An episode nothing curated holds is a fact worth logging; invented progress would be a lie."""
    read = WatchEventRead.model_validate(_stored_event(curated_entry_id=None, category_id=None))

    assert read.curated_entry_id is None
    assert read.progress is None


# -- the TypeScript mirrors --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("model", "name"),
    [(WatchEventCreate, "WatchEventCreate"), (WatchEventRead, "WatchEventRead")],
    ids=["WatchEventCreate", "WatchEventRead"],
)
def test_the_typescript_mirrors_carry_the_same_snake_case_fields(model: type[BaseModel], name: str) -> None:
    assert ts_fields(name) == list(model.model_fields)


def test_the_response_mirror_has_no_optional_keys_and_the_request_mirror_does() -> None:
    """A response serialises every field, so a nullable one is `T | null`; a request's defaults are `?:`."""
    assert TS_OPTIONAL_KEY not in ts_source("WatchEventRead")
    assert TS_OPTIONAL_KEY in ts_source("WatchEventCreate")


@pytest.mark.parametrize(
    ("file_name", "declared"),
    [
        ("WatchEventCreate", 'export type WatchSubjectKind = "episode" | "title" | "curated_entry";'),
        ("WatchEventRead", 'export type WatchEventSource = "ui" | "excel_mirror" | "player";'),
    ],
    ids=["WatchSubjectKind", "WatchEventSource"],
)
def test_the_typescript_mirror_spells_each_enum_the_way_postgres_labels_it(file_name: str, declared: str) -> None:
    assert declared in ts_source(file_name).splitlines()
