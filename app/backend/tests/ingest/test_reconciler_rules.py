"""The reconciler's decisions, proved without a database: identity, adoption, refusal, span, position."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tv_watchlist.constants import ADOPTION_POSITION_WINDOW, MISMATCH_REFUSAL_RATIO
from tv_watchlist.data.enums import MediaType, ResolutionState, UnitKind
from tv_watchlist.data.models import Category, CuratedEntry, Title
from tv_watchlist.ingest.reconcile_outcome import ReconcileOutcome
from tv_watchlist.ingest.reconciler import (
    NOT_CONFIGURED_NOTE,
    Reconciler,
    _entry_match_key,
    _leave_unresolved,
    _note_unconfigured,
    _refusal_label,
    _RowPlan,
    _store_resolution,
    _unchanged,
    _wanted,
    adoption_match,
    identities_intact,
    is_near_total_mismatch,
    malformed_identity_rows,
    needs_resolution,
    parsed_identity,
    renumbered,
    span_values,
)
from tv_watchlist.models.watch_row import WatchRow
from tv_watchlist.resolver.span import SpanParse
from tv_watchlist.resolver.title_resolution import TitleResolution
from tv_watchlist.services.catalog import Catalog
from tv_watchlist.workbook.errors import StaleWorkbookError, WorkbookError, WorkbookLockedError

A_UUID = uuid.UUID("2f1d1f3a-9a4d-4a1e-9a3e-6f3f2b7c8d90")
A_DIGEST = "a" * 64
A_KEY = "max 2002"
A_UNIT = "E1-3"
A_NOTE = "nothing matched this row"


def _row(number: int) -> WatchRow:
    return WatchRow(row=number, cells={"title": "Max"})


def _entry(position: int, *, match_key: str | None = A_KEY, raw_unit: str = A_UNIT) -> CuratedEntry:
    return CuratedEntry(
        id=uuid.uuid4(), category_id=uuid.uuid4(), position=position, match_key=match_key, raw_unit=raw_unit
    )


def _resolution(state: ResolutionState, confidence: Decimal) -> TitleResolution:
    return TitleResolution(
        state=state, confidence=confidence, note=A_NOTE, chosen=None, alternatives=(), unit_kind=UnitKind.EPISODES
    )


def _span(kind: UnitKind, *, start: int | None = None, end: int | None = None, season: int | None = None) -> SpanParse:
    return SpanParse(
        unit_kind=kind,
        order_type=None,
        span_start=start,
        span_end=end,
        season_number=season,
        confidence=Decimal("0.90"),
        note="",
    )


@pytest.mark.parametrize(
    "text",
    ["", "   ", "not-a-uuid", "{2f1d1f3a-9a4d-4a1e-9a3e-6f3f2b7c8d90}", "2f1d1f3a9a4d4a1e9a3e6f3f2b7c8d90"],
)
def test_only_the_canonical_36_character_form_parses(text: str) -> None:
    """Ruling 20: braces, bare hex and URNs were typed by a human, not written by this app."""
    assert parsed_identity(text) is None


def test_a_canonical_uuid_parses_whatever_its_case(text: str = f"{A_UUID}".upper()) -> None:
    assert parsed_identity(text) == A_UUID
    assert parsed_identity(f" {A_UUID} ") == A_UUID


def test_a_non_uuid_cell_is_reported_and_a_blank_one_is_not() -> None:
    rows = [_row(2), _row(3), _row(4)]
    row_ids = {2: "", 3: "typed by hand", 4: str(A_UUID)}

    assert malformed_identity_rows(rows, row_ids) == [3]


def test_adoption_needs_title_unit_and_position_to_agree_at_once() -> None:
    right = _entry(5)
    wrong_unit = _entry(5, raw_unit="E4-9")
    wrong_title = _entry(5, match_key="something else 1999")
    far_away = _entry(5 + ADOPTION_POSITION_WINDOW + 1)

    found = adoption_match(
        [right, wrong_unit, wrong_title, far_away], position=5, match_key=A_KEY, raw_unit=A_UNIT, window=3
    )

    assert found is right


def test_the_window_is_inclusive_at_its_edge() -> None:
    edge = _entry(5 + ADOPTION_POSITION_WINDOW)

    assert adoption_match([edge], position=5, match_key=A_KEY, raw_unit=A_UNIT) is edge


def test_two_equally_good_candidates_adopt_neither() -> None:
    """A season-per-row workbook names one show a dozen times; an ambiguous match would re-key history."""
    found = adoption_match([_entry(4), _entry(6)], position=5, match_key=A_KEY, raw_unit=A_UNIT, window=3)

    assert found is None


def test_a_first_ingest_is_never_a_near_total_mismatch() -> None:
    assert is_near_total_mismatch(100, 100, previously_ingested=False) is False


def test_an_empty_sheet_is_never_a_near_total_mismatch() -> None:
    assert is_near_total_mismatch(0, 0, previously_ingested=True) is False


@pytest.mark.parametrize(
    ("unmatched", "expected"),
    [(49, False), (50, True), (100, True)],
)
def test_the_refusal_ratio_is_the_documented_share(unmatched: int, expected: bool) -> None:
    assert MISMATCH_REFUSAL_RATIO == 0.5
    assert is_near_total_mismatch(100, unmatched, previously_ingested=True) is expected


def test_a_confirmed_entry_whose_cells_did_not_move_is_never_re_resolved() -> None:
    assert needs_resolution(ResolutionState.CONFIRMED, is_new=False, raws_changed=False) is False


def test_a_confirmed_entry_whose_cells_moved_is_resolved_again() -> None:
    assert needs_resolution(ResolutionState.CONFIRMED, is_new=True, raws_changed=True) is True


def test_a_rejected_entry_is_left_alone_until_its_cells_move() -> None:
    assert needs_resolution(ResolutionState.REJECTED, is_new=False, raws_changed=False) is False
    assert needs_resolution(ResolutionState.REJECTED, is_new=False, raws_changed=True) is True


def test_an_unresolved_entry_is_always_worth_another_try() -> None:
    assert needs_resolution(ResolutionState.UNRESOLVED, is_new=False, raws_changed=False) is True


def test_an_auto_entry_is_revisited_only_when_its_own_cells_moved() -> None:
    """The six-month ceiling refreshes the cached payload; it never re-opens which work a row means."""
    assert needs_resolution(ResolutionState.AUTO, is_new=False, raws_changed=False) is False
    assert needs_resolution(ResolutionState.AUTO, is_new=False, raws_changed=True) is True


def test_an_episode_span_is_read_through_its_own_accessor() -> None:
    assert span_values(_span(UnitKind.EPISODES, start=19, end=53)) == (None, 19, 53, None)


def test_a_kind_without_bounds_yields_no_half_span() -> None:
    """Ruling 29: `episode_span` is None when either bound is missing, and nothing leaks out of it."""
    assert span_values(_span(UnitKind.EPISODES, start=19)) == (None, None, None, None)


def test_a_movie_has_no_span_at_all() -> None:
    assert span_values(_span(UnitKind.MOVIE)) == (None, None, None, None)


def test_a_season_range_reads_through_the_season_accessor() -> None:
    assert span_values(_span(UnitKind.SEASON, start=1, end=3, season=1)) == (None, 1, 3, 1)


def test_a_second_pass_episode_match_overrides_the_unit_cell() -> None:
    """The row was found by name inside a series; its own season and episode are what it means."""
    assert span_values(_span(UnitKind.UNKNOWN), season_number=0, episode_number=7) == (None, 7, 7, 0)


def test_a_second_pass_season_match_carries_the_season_and_no_episode_bounds() -> None:
    assert span_values(_span(UnitKind.UNKNOWN), season_number=2) == (None, None, None, 2)


def test_live_rows_take_the_sheets_order_and_retired_ones_queue_behind_them() -> None:
    """`uq(category_id, position)` covers soft-deleted rows too, so they cannot keep a live position."""
    live = [uuid.uuid4() for _ in range(3)]
    retired = [uuid.uuid4(), uuid.uuid4()]

    positions = renumbered(live, retired)

    assert [positions[entry_id] for entry_id in live] == [1, 2, 3]
    assert [positions[entry_id] for entry_id in retired] == [4, 5]
    assert len(set(positions.values())) == len(positions)


def test_a_category_with_no_digest_yet_is_never_unchanged() -> None:
    assert _unchanged(Category(slug="x", file_name="x", sheet_title="x", accent="#000000"), A_DIGEST) is False


def _identified(row: int, entry_id: uuid.UUID, *, removed: bool = False) -> CuratedEntry:
    entry = CuratedEntry(id=entry_id, category_id=uuid.uuid4(), position=row - 1, sheet_row=row)
    if removed:
        entry.removed_at = datetime(2026, 9, 20, tzinfo=UTC)
    return entry


def test_identities_are_intact_when_every_cell_is_the_one_this_app_wrote() -> None:
    first, second = uuid.uuid4(), uuid.uuid4()

    assert identities_intact([_identified(2, first), _identified(3, second)], {2: str(first), 3: str(second)}) is True


def test_a_cleared_identity_column_is_never_intact_however_unchanged_the_grid_is() -> None:
    """Ruling 49's corner: the Row ID column is outside the digest, so only this half can catch it."""
    assert identities_intact([_identified(2, uuid.uuid4())], {}) is False


def test_a_duplicated_blanked_or_hand_typed_identity_is_never_intact() -> None:
    first, second = uuid.uuid4(), uuid.uuid4()
    entries = [_identified(2, first), _identified(3, second)]

    assert identities_intact(entries, {2: str(first), 3: str(first)}) is False
    assert identities_intact(entries, {2: str(first), 3: "typed by hand"}) is False
    assert identities_intact(entries, {2: str(first), 3: ""}) is False


def test_a_retired_entry_owns_no_cell_and_so_does_not_break_the_comparison() -> None:
    live, gone = uuid.uuid4(), uuid.uuid4()
    entries = [_identified(2, live), _identified(3, gone, removed=True)]

    assert identities_intact(entries, {2: str(live)}) is True


def test_the_change_test_is_the_digest_alone_whatever_the_stamp_says() -> None:
    """Ruling 49: an Excel resave moves the stamp over identical bytes, which is not a change."""
    category = Category(slug="x", file_name="x", sheet_title="x", accent="#000000")
    category.workbook_mtime, category.workbook_digest = 1_700_000_000.5, A_DIGEST

    assert _unchanged(category, A_DIGEST) is True
    assert _unchanged(category, "b" * 64) is False
    # The stamp is not consulted at all: a file ten seconds newer with the same grid is still unchanged.
    category.workbook_mtime = 1_700_000_010.5
    assert _unchanged(category, A_DIGEST) is True


def _plan(
    *, state: ResolutionState = ResolutionState.UNRESOLVED, is_new: bool = False, raws_changed: bool = False
) -> _RowPlan:
    entry = _entry(1)
    entry.resolution_state = state
    return _RowPlan(
        row=_row(2),
        position=1,
        entry=entry,
        is_new=is_new,
        raws_changed=raws_changed,
        identity_to_write=None,
    )


def test_wanted_reads_the_three_facts_off_the_plan() -> None:
    """The one place `needs_resolution`'s inputs are spelled out, so they cannot be read two ways."""
    assert _wanted(_plan(state=ResolutionState.AUTO)) is False
    assert _wanted(_plan(state=ResolutionState.AUTO, raws_changed=True)) is True
    assert _wanted(_plan(state=ResolutionState.AUTO, is_new=True)) is True
    assert _wanted(_plan(state=ResolutionState.CONFIRMED, raws_changed=False)) is False


def test_the_match_key_is_the_normalised_title_with_the_release_year_appended() -> None:
    assert _entry_match_key("The Sound of Music", "1965") == "sound of music 1965"
    # A free-text Release cell that does not open with a year contributes none, and is never coerced.
    assert _entry_match_key("Max", "some time in 2002") == "max"


def test_a_blank_title_has_no_match_key_at_all() -> None:
    """`None` rather than `""`: a nullable column with one absent form is what adoption compares on."""
    assert _entry_match_key("", "") is None


def test_the_match_key_is_clipped_to_the_column_the_schema_declared() -> None:
    """T19's helper, not a second clip: one character over `String(255)` aborts the whole transaction."""
    declared = CuratedEntry.__table__.columns["match_key"].type.length
    key = _entry_match_key("a" * (declared * 2), "")

    assert declared == 255
    assert key is not None
    assert len(key) == declared


def test_leaving_an_entry_unresolved_drops_the_title_and_records_the_reason() -> None:
    entry = _entry(1)
    entry.title_id, entry.resolution_state = uuid.uuid4(), ResolutionState.AUTO

    _leave_unresolved(entry, A_NOTE)

    assert (entry.title_id, entry.resolution_state, entry.resolution_note) == (
        None,
        ResolutionState.UNRESOLVED,
        A_NOTE,
    )


def test_an_unconfigured_pass_notes_a_resolved_entry_without_undoing_it() -> None:
    """A human's `confirmed` is not undone because a token was absent, even when the cells moved."""
    entry = _entry(1)
    entry.title_id = uuid.uuid4()
    entry.resolution_state = ResolutionState.CONFIRMED
    entry.resolution_confidence = Decimal("0.95")
    standing = entry.title_id

    _note_unconfigured(entry)

    assert (entry.title_id, entry.resolution_state) == (standing, ResolutionState.CONFIRMED)
    assert entry.resolution_confidence == Decimal("0.95")
    assert entry.resolution_note == NOT_CONFIGURED_NOTE


def test_an_unconfigured_pass_still_leaves_a_never_resolved_entry_unresolved() -> None:
    """Which is what makes the next configured pass pick it up again."""
    entry = _entry(1)
    entry.resolution_state = ResolutionState.AUTO

    _note_unconfigured(entry)

    assert (entry.title_id, entry.resolution_state) == (None, ResolutionState.UNRESOLVED)
    assert entry.resolution_note == NOT_CONFIGURED_NOTE


def test_a_resolution_is_stored_with_its_confidence_faithfully() -> None:
    """T30/T57's review queue keys on `unresolved OR confidence < 0.80`, so the number is not rounded."""
    entry = _entry(1)
    title = Title(id=uuid.uuid4(), media_type=MediaType.TV, tmdb_id=37854, name="One Piece", match_key="one piece")

    _store_resolution(
        entry,
        _resolution(ResolutionState.AUTO, Decimal("0.65")),
        title,
        _span(UnitKind.EPISODES, start=19, end=53),
    )

    assert entry.title_id == title.id
    assert (entry.resolution_state, entry.resolution_confidence) == (ResolutionState.AUTO, Decimal("0.65"))
    assert (entry.span_start, entry.span_end) == (19, 53)
    assert entry.unit_kind is UnitKind.EPISODES


def test_a_tie_is_stored_as_any_other_unresolved_row() -> None:
    """Ruling 35: no candidate, so no title_id - the note and the confidence are the whole answer."""
    entry = _entry(1)
    entry.title_id = uuid.uuid4()

    _store_resolution(entry, _resolution(ResolutionState.UNRESOLVED, Decimal("0.50")), None, _span(UnitKind.UNKNOWN))

    assert entry.title_id is None
    assert (entry.resolution_state, entry.resolution_confidence) == (ResolutionState.UNRESOLVED, Decimal("0.50"))
    assert (entry.span_start, entry.span_end, entry.season_number) == (None, None, None)


def test_a_second_pass_match_stores_the_unit_it_was_found_at() -> None:
    entry = _entry(1)
    title = Title(id=uuid.uuid4(), media_type=MediaType.TV, tmdb_id=1, name="x", match_key="x")

    _store_resolution(entry, _resolution(ResolutionState.AUTO, Decimal("0.50")), title, _span(UnitKind.UNKNOWN), 0, 7)

    assert (entry.span_start, entry.span_end, entry.season_number) == (7, 7, 0)


@pytest.mark.parametrize(
    ("refusal", "expected"),
    [(WorkbookLockedError("x"), "locked"), (StaleWorkbookError("x"), "stale"), (WorkbookError("x"), "workbook")],
)
def test_every_workbook_refusal_has_its_own_one_word_label(refusal: WorkbookError, expected: str) -> None:
    assert _refusal_label(refusal) == expected


def test_a_workbook_that_refused_the_write_logs_its_own_end_record(caplog: pytest.LogCaptureFixture) -> None:
    """A `reconcile_start` with no `reconcile_end` after it reads as a crash, not as Excel holding the file."""
    reconciler = Reconciler(
        cast("AsyncSession", object()), cast("Catalog", object()), resolver=None, tmdb_ingest=None, order_ingest=None
    )

    with caplog.at_level(logging.INFO, logger="tv_watchlist.ingest.reconciler"):
        reconciler._logged(ReconcileOutcome(slug="marvel"), 0.0, refused=_refusal_label(WorkbookLockedError("x")))

    record = caplog.records[-1].getMessage()
    assert record.startswith("reconcile_end job=reconcile category=marvel")
    assert "refused=locked" in record
    assert "elapsed_ms=" in record


def test_an_ordinary_end_record_says_it_refused_nothing(caplog: pytest.LogCaptureFixture) -> None:
    reconciler = Reconciler(
        cast("AsyncSession", object()), cast("Catalog", object()), resolver=None, tmdb_ingest=None, order_ingest=None
    )

    with caplog.at_level(logging.INFO, logger="tv_watchlist.ingest.reconciler"):
        reconciler._logged(ReconcileOutcome(slug="marvel", minted=3), 0.0)

    assert "refused=none" in caplog.records[-1].getMessage()
