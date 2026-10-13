"""The mirror's vocabulary: five derived kinds onto four cell values, and the echo defence around them.

Everything here is offline and pure. The projection is a lookup table and its inverse, the human-edit
test is one comparison, and the throttle is another - so none of it needs a database or a workbook, and
all of it is the part that must never drift (CLAUDE.md section 5.16, section 11.2 rules 12-13).
"""

from __future__ import annotations

import ast
import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest

from tv_watchlist.constants import (
    DEFAULT_WATCH_CHOICES,
    IN_PROGRESS,
    MAX_CELL_LENGTH,
    MAX_MIRROR_NOTE_LITERAL,
    MIRROR_NOTE_TEMPLATE,
    SKIPPED,
    UNWATCHED,
    WATCH_HEADER_LABEL,
    WATCHED,
)
from tv_watchlist.data.enums import WatchEventKind, WatchEventSource, WatchSubjectKind
from tv_watchlist.data.models import CuratedEntry, WatchEvent
from tv_watchlist.models.column_spec import ColumnKind, ColumnSpec
from tv_watchlist.services import watch_mirror
from tv_watchlist.services.watch_mirror import (
    human_edit_events,
    kind_for_cell,
    pending_mirror_cells,
    record_mirrored,
    watch_cell,
    writable_mirror_cells,
)

NOW: Final[datetime] = datetime(2026, 9, 20, 13, 0, tzinfo=UTC)
A_ROW: Final[int] = 2
A_CATEGORY: Final[str] = "a-category"
# A status dropdown a hand-made sheet may carry instead of the library's four values.
A_FOREIGN_VOCABULARY: Final[tuple[str, ...]] = ("Yes", "No")
# Read off the column rather than restated: the note must fit whatever width the schema declares.
_NOTE_COLUMN_WIDTH: Final[int] = WatchEvent.__table__.c.note.type.length
# CLAUDE.md section 5.16 states this table; it is repeated here as the reference value the code is
# checked against, rather than read back out of the module under test.
EXPECTED_PROJECTION: Final[dict[WatchEventKind, str]] = {
    WatchEventKind.COMPLETED: WATCHED,
    WatchEventKind.SKIPPED: SKIPPED,
    WatchEventKind.STARTED: IN_PROGRESS,
    WatchEventKind.PROGRESSED: IN_PROGRESS,
    WatchEventKind.UNSET: UNWATCHED,
}


def _entry(*, mirrored: str | None = None, row: int | None = A_ROW, removed: datetime | None = None) -> CuratedEntry:
    """One transient entry. `mirrored=None` is a row this app has never written a cell for."""
    entry = CuratedEntry(id=uuid.uuid4(), category_id=uuid.uuid4(), position=1, sheet_row=row, removed_at=removed)
    if mirrored is not None:
        entry.mirrored_watch_cell = mirrored
    return entry


# -- the projection ---------------------------------------------------------------------------------


def test_the_five_kinds_project_onto_exactly_four_cell_values() -> None:
    """The reference table itself: five derived kinds, four values, the two in-progress kinds sharing one."""
    projected = {kind: watch_cell(kind) for kind in WatchEventKind}

    assert projected == EXPECTED_PROJECTION
    assert set(projected.values()) == {UNWATCHED, WATCHED, IN_PROGRESS, SKIPPED}


@pytest.mark.parametrize("kind", list(WatchEventKind))
def test_every_kind_the_view_can_return_has_a_projection(kind: WatchEventKind) -> None:
    """The view collapses a roll-up into one of these; a kind with no cell would raise mid-write."""
    assert watch_cell(kind) in EXPECTED_PROJECTION.values()


def test_no_cell_value_is_re_declared_as_a_literal() -> None:
    """The vocabulary lives once, in constants.py. Read as string constants, so prose may still say it."""
    source = Path(str(watch_mirror.__file__)).read_text(encoding="utf-8")
    spelled = {
        node.value for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Constant) and type(node.value) is str
    }

    assert spelled.isdisjoint({UNWATCHED, WATCHED, IN_PROGRESS, SKIPPED})


# -- the inverse, for a cell a human typed -----------------------------------------------------------


@pytest.mark.parametrize(
    ("cell", "expected"),
    [
        (WATCHED, WatchEventKind.COMPLETED),
        (SKIPPED, WatchEventKind.SKIPPED),
        (IN_PROGRESS, WatchEventKind.STARTED),
        (UNWATCHED, WatchEventKind.UNSET),
    ],
)
def test_each_of_the_four_values_reads_back_as_a_kind(cell: str, expected: WatchEventKind) -> None:
    assert kind_for_cell(cell) is expected


def test_the_in_progress_value_reads_back_as_started_never_progressed() -> None:
    """`progressed_has_position` is a database CHECK, and a cell carries no position."""
    assert kind_for_cell(IN_PROGRESS) is not WatchEventKind.PROGRESSED


@pytest.mark.parametrize("cell", ["Watched?", "watched", "Done", "Skipped", "In-progress", "  ?  "])
def test_text_outside_the_four_values_reads_back_as_nothing(cell: str) -> None:
    """A typo is text the app never wrote and cannot read; it is never guessed at."""
    assert kind_for_cell(cell) is None


@pytest.mark.parametrize("cell", [f" {WATCHED} ", f"{SKIPPED}\t", f"\n{IN_PROGRESS}"])
def test_surrounding_whitespace_does_not_hide_a_value(cell: str) -> None:
    assert kind_for_cell(cell) is not None


# -- human edits, and the echo that is not one -------------------------------------------------------


def test_a_human_edit_appends_one_entry_level_excel_mirror_event_with_the_literal_text() -> None:
    entry = _entry(mirrored=UNWATCHED)

    events = human_edit_events([entry], {entry.id: WATCHED}, now=NOW)

    assert len(events) == 1
    event = events[0]
    assert event.subject_kind is WatchSubjectKind.CURATED_ENTRY
    assert event.kind is WatchEventKind.COMPLETED
    assert event.source is WatchEventSource.EXCEL_MIRROR
    assert event.curated_entry_id == entry.id
    assert event.category_id == entry.category_id
    assert event.occurred_at == NOW
    assert event.note is not None and WATCHED in event.note
    # An entry-level event is exactly that: it touches no episode and no title (the `one_subject` CHECK).
    assert event.episode_id is None
    assert event.title_id is None


def test_our_own_echo_appends_no_event() -> None:
    """The whole defence against the mirror loop: what we last wrote is not a human edit."""
    entry = _entry(mirrored=WATCHED)

    assert human_edit_events([entry], {entry.id: WATCHED}, now=NOW) == []


def test_an_empty_cell_on_a_row_never_mirrored_is_not_an_edit() -> None:
    """A row the app has never written is `None`, not `""` - and an empty cell has not been moved."""
    entry = _entry(mirrored=None)

    assert entry.mirrored_watch_cell is None
    assert human_edit_events([entry], {entry.id: UNWATCHED}, now=NOW) == []


def test_a_first_ingest_captures_a_mark_the_owner_had_already_made() -> None:
    """996 rows arrive already marked; without this the app would report nothing watched."""
    entry = _entry(mirrored=None)

    events = human_edit_events([entry], {entry.id: SKIPPED}, now=NOW)

    assert [event.kind for event in events] == [WatchEventKind.SKIPPED]


def test_clearing_a_cell_by_hand_is_an_unset_event() -> None:
    entry = _entry(mirrored=WATCHED)

    events = human_edit_events([entry], {entry.id: UNWATCHED}, now=NOW)

    assert [event.kind for event in events] == [WatchEventKind.UNSET]


def test_a_cell_padded_by_hand_is_still_our_own_echo() -> None:
    """The comparison and the reading strip the same way, so padding cannot read as an edit."""
    entry = _entry(mirrored=WATCHED)

    assert human_edit_events([entry], {entry.id: f"  {WATCHED}\t"}, now=NOW) == []


def test_an_entry_the_sheet_did_not_report_gets_no_event() -> None:
    """A workbook with no watch column reports no cell at all, and that is not an edit."""
    entry = _entry(mirrored=WATCHED)

    assert human_edit_events([entry], {}, now=NOW) == []


def test_text_outside_the_four_values_appends_no_event_but_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    entry = _entry(mirrored=UNWATCHED)
    typo = f"{WATCHED}?"

    with caplog.at_level(logging.INFO, logger=watch_mirror.__name__):
        events = human_edit_events([entry], {entry.id: typo}, now=NOW)

    assert events == []
    assert any("mirror_unknown_cell" in record.message for record in caplog.records)
    assert any(typo in record.getMessage() for record in caplog.records)


def test_hostile_text_in_an_unrecognised_cell_cannot_forge_a_log_line(caplog: pytest.LogCaptureFixture) -> None:
    """A status column is free text until somebody types in it (section 10.3, B14 and log injection)."""
    entry = _entry(mirrored=UNWATCHED)
    hostile = "\r\nmirror_written job=mirror category=elsewhere " + "x" * MAX_CELL_LENGTH

    with caplog.at_level(logging.INFO, logger=watch_mirror.__name__):
        assert human_edit_events([entry], {entry.id: hostile}, now=NOW) == []

    logged = next(record.getMessage() for record in caplog.records if "mirror_unknown_cell" in record.message)
    echoed = logged.split("cell=", 1)[1]
    assert "\n" not in logged and "\r" not in logged
    assert len(echoed) == MAX_MIRROR_NOTE_LITERAL


def test_a_padded_cell_still_produces_a_bounded_single_line_note() -> None:
    """The note is the literal the owner typed, echoed - so it is normalised before it is stored."""
    entry = _entry(mirrored=UNWATCHED)

    events = human_edit_events([entry], {entry.id: f" \t{WATCHED}\r\n "}, now=NOW)

    note = events[0].note
    assert note == MIRROR_NOTE_TEMPLATE.format(literal=WATCHED)
    assert len(note) <= len(MIRROR_NOTE_TEMPLATE.format(literal=UNWATCHED)) + MAX_MIRROR_NOTE_LITERAL
    assert len(note) <= _NOTE_COLUMN_WIDTH


def test_one_event_per_edited_entry_and_none_for_the_rest() -> None:
    edited, echoed, untouched = _entry(mirrored=UNWATCHED), _entry(mirrored=WATCHED), _entry(mirrored=SKIPPED)
    observed = {edited.id: WATCHED, echoed.id: WATCHED, untouched.id: SKIPPED}

    events = human_edit_events([edited, echoed, untouched], observed, now=NOW)

    assert [event.curated_entry_id for event in events] == [edited.id]


# -- the throttle ------------------------------------------------------------------------------------


def test_only_entries_whose_projection_moved_are_written_back() -> None:
    moved, standing = _entry(mirrored=UNWATCHED), _entry(mirrored=WATCHED)
    states = {moved.id: WatchEventKind.COMPLETED, standing.id: WatchEventKind.COMPLETED}

    assert pending_mirror_cells([moved, standing], states) == {moved.id: WATCHED}


def test_a_row_never_mirrored_whose_state_is_unset_is_not_written() -> None:
    """Otherwise every one of 996 rows would be rewritten on the first pass to say nothing."""
    entry = _entry(mirrored=None)

    assert pending_mirror_cells([entry], {entry.id: WatchEventKind.UNSET}) == {}


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        (WatchEventKind.COMPLETED, WATCHED),
        (WatchEventKind.SKIPPED, SKIPPED),
        (WatchEventKind.STARTED, IN_PROGRESS),
        (WatchEventKind.PROGRESSED, IN_PROGRESS),
    ],
)
def test_each_derived_state_is_written_as_its_own_cell_value(kind: WatchEventKind, expected: str) -> None:
    entry = _entry(mirrored=UNWATCHED)

    assert pending_mirror_cells([entry], {entry.id: kind}) == {entry.id: expected}


def test_a_soft_deleted_entry_is_never_written_back() -> None:
    """Nothing in the curated chain is hard-deleted, and a retired row has no cell left to write."""
    entry = _entry(mirrored=UNWATCHED, removed=NOW)

    assert pending_mirror_cells([entry], {entry.id: WatchEventKind.COMPLETED}) == {}


def test_an_entry_whose_row_left_the_sheet_is_never_written_back() -> None:
    entry = _entry(mirrored=UNWATCHED, row=None)

    assert pending_mirror_cells([entry], {entry.id: WatchEventKind.COMPLETED}) == {}


def test_an_entry_the_view_says_nothing_about_is_never_written_back() -> None:
    entry = _entry(mirrored=UNWATCHED)

    assert pending_mirror_cells([entry], {}) == {}


# -- remembering what was written --------------------------------------------------------------------


def test_record_mirrored_remembers_only_what_was_written() -> None:
    written, skipped = _entry(mirrored=UNWATCHED), _entry(mirrored=UNWATCHED)

    record_mirrored([written, skipped], {written.id: WATCHED})

    assert written.mirrored_watch_cell == WATCHED
    assert skipped.mirrored_watch_cell == UNWATCHED


def test_a_recorded_cell_makes_the_next_read_of_it_an_echo() -> None:
    """The round trip in one line: what `record_mirrored` stores is what `human_edit_events` forgives."""
    entry = _entry(mirrored=UNWATCHED)

    record_mirrored([entry], {entry.id: WATCHED})

    assert human_edit_events([entry], {entry.id: WATCHED}, now=NOW) == []


# -- the sheet's own vocabulary wins (Ruling 41) -----------------------------------------------------


def _column(kind: ColumnKind, choices: Sequence[str]) -> ColumnSpec:
    return ColumnSpec(key="watched", label=WATCH_HEADER_LABEL, index=8, kind=kind, role="watch", choices=list(choices))


def test_a_text_status_column_has_no_vocabulary_to_contradict() -> None:
    entry = _entry(mirrored=UNWATCHED)
    pending = {entry.id: WATCHED}

    assert writable_mirror_cells(pending, _column("text", []), category=A_CATEGORY) == pending


def test_the_library_s_own_dropdown_offers_every_value_the_mirror_writes() -> None:
    """The nineteen workbooks all offer exactly these, so nothing is ever dropped for one of them."""
    entries = [_entry(mirrored=UNWATCHED) for _ in DEFAULT_WATCH_CHOICES]
    pending = dict(zip((entry.id for entry in entries), DEFAULT_WATCH_CHOICES, strict=True))

    assert writable_mirror_cells(pending, _column("choice", DEFAULT_WATCH_CHOICES), category=A_CATEGORY) == pending


def test_a_dropdown_offering_something_else_drops_the_cell_rather_than_the_pass(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """`writer._validate` refuses the whole write on the first value it does not know, and on the ingest
    path that rolls the entire pass back - so one odd sheet would be permanently un-ingestable."""
    entry = _entry(mirrored=UNWATCHED)

    with caplog.at_level(logging.INFO, logger=watch_mirror.__name__):
        column = _column("choice", A_FOREIGN_VOCABULARY)
        writable = writable_mirror_cells({entry.id: WATCHED}, column, category=A_CATEGORY)

    assert writable == {}
    assert any("mirror_skipped_cell" in record.message for record in caplog.records)
    logged = next(record.getMessage() for record in caplog.records if "mirror_skipped_cell" in record.message)
    assert f"category={A_CATEGORY}" in logged
    assert f"entry={entry.id}" in logged
    assert "skipped=invalid_choice" in logged


def test_only_the_values_the_dropdown_refuses_are_dropped() -> None:
    offered, refused = _entry(mirrored=UNWATCHED), _entry(mirrored=UNWATCHED)
    column = _column("choice", (UNWATCHED, WATCHED))

    writable = writable_mirror_cells({offered.id: WATCHED, refused.id: SKIPPED}, column, category=A_CATEGORY)

    assert writable == {offered.id: WATCHED}


def test_a_dropped_cell_leaves_its_entry_claiming_no_write() -> None:
    """The point of filtering rather than failing: nothing may say it wrote a cell it never wrote."""
    offered, refused = _entry(mirrored=UNWATCHED), _entry(mirrored=UNWATCHED)
    column = _column("choice", (UNWATCHED, WATCHED))
    pending = {offered.id: WATCHED, refused.id: SKIPPED}

    record_mirrored([offered, refused], writable_mirror_cells(pending, column, category=A_CATEGORY))

    assert offered.mirrored_watch_cell == WATCHED
    assert refused.mirrored_watch_cell == UNWATCHED
