"""The review queue's pure half: what each decision writes, and the one query the listing compiles to.

No database and no provider - these are functions of their arguments, the same split the reconciler's
rules module draws. The state machine is what master plan rule 5 is about, so it is asserted here where
it can be asserted everywhere, rather than only where a Postgres is listening.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Final

import pytest
from sqlalchemy.dialects import postgresql

from tv_watchlist.constants import CONFIRMED_RESOLUTION_CONFIDENCE, MAX_REASON_LENGTH, REVIEW_NOTE_PREFIX
from tv_watchlist.data.enums import ResolutionState, UnitKind
from tv_watchlist.data.models import CuratedEntry
from tv_watchlist.ingest.expansion import NOTE_JOIN, QUEUE_NOTE_PREFIX
from tv_watchlist.ingest.reconciler import needs_resolution
from tv_watchlist.models.resolution_update import ResolutionUpdate
from tv_watchlist.services.resolution_review import (
    DEFAULT_REVIEW_STATES,
    confirmed,
    rejected,
    review_queue_statement,
    reviewed,
)

A_PAGE: Final[int] = 25
A_RESOLVER_CLAUSE: Final[str] = "auto: 0.65 on title and year"
A_QUEUE_CLAUSE: Final[str] = f"{QUEUE_NOTE_PREFIX}absolute carries 35 of the 35 asked for"


def _an_auto_entry() -> CuratedEntry:
    """A transient row in the state the queue finds them in. Nothing here is flushed."""
    return CuratedEntry(
        position=1,
        unit_kind=UnitKind.EPISODES,
        resolution_state=ResolutionState.AUTO,
        resolution_confidence=Decimal("0.50"),
        resolution_note=A_RESOLVER_CLAUSE,
        raw_cells={},
        order_type="absolute",
        order_label="Specials",
        span_start=19,
        span_end=53,
        season_number=2,
    )


def test_confirming_pins_the_row_at_a_confidence_no_heuristic_can_produce() -> None:
    entry = _an_auto_entry()

    confirmed(entry)

    assert entry.resolution_state is ResolutionState.CONFIRMED
    assert entry.resolution_confidence == CONFIRMED_RESOLUTION_CONFIDENCE == Decimal("1.00")


def test_confirming_moves_nothing_about_the_match_itself() -> None:
    """A confirmation says the standing answer is right; rewriting it would make that a correction."""
    entry = _an_auto_entry()

    confirmed(entry)

    assert (entry.order_type, entry.span_start, entry.span_end, entry.season_number) == ("absolute", 19, 53, 2)


def test_rejecting_clears_the_match_and_the_confidence_with_it() -> None:
    entry = _an_auto_entry()

    rejected(entry)

    assert entry.resolution_state is ResolutionState.REJECTED
    assert entry.resolution_confidence is None
    assert (entry.order_type, entry.span_start, entry.span_end, entry.season_number) == (None, None, None, None)
    assert entry.order_label == ""


def test_rejecting_leaves_the_sheet_s_own_row_alone() -> None:
    entry = _an_auto_entry()
    entry.raw_cells = {"title": "Making of"}

    rejected(entry)

    assert entry.position == 1
    assert entry.raw_cells == {"title": "Making of"}


@pytest.mark.parametrize(
    ("state", "action"),
    [
        (ResolutionState.CONFIRMED, confirmed),
        (ResolutionState.REJECTED, rejected),
    ],
    ids=["confirmed", "rejected"],
)
def test_a_settled_row_is_never_re_resolved_until_its_cells_move(
    state: ResolutionState, action: Callable[[CuratedEntry], None]
) -> None:
    """Rule 5, against the reconciler's own predicate rather than a restatement of it."""
    entry = _an_auto_entry()

    action(entry)

    assert entry.resolution_state is state
    assert needs_resolution(entry.resolution_state, is_new=False, raws_changed=False) is False
    assert needs_resolution(entry.resolution_state, is_new=False, raws_changed=True) is True


# -- the note --------------------------------------------------------------------------------------


def test_a_review_clause_is_added_beside_the_resolvers_own_words() -> None:
    note = reviewed(A_RESOLVER_CLAUSE, ResolutionUpdate(action="confirm", note="checked the box set"))

    assert note.startswith(A_RESOLVER_CLAUSE)
    assert f"{REVIEW_NOTE_PREFIX}confirm - checked the box set" in note


def test_a_second_review_replaces_the_first_and_keeps_everything_else() -> None:
    first = reviewed(f"{A_RESOLVER_CLAUSE}{NOTE_JOIN}{A_QUEUE_CLAUSE}", ResolutionUpdate(action="confirm"))

    second = reviewed(first, ResolutionUpdate(action="reject", note="a featurette"))

    assert second.count(REVIEW_NOTE_PREFIX) == 1
    assert f"{REVIEW_NOTE_PREFIX}reject - a featurette" in second
    # The resolver's sentence and the queue's are not this function's to remove.
    assert A_RESOLVER_CLAUSE in second and A_QUEUE_CLAUSE in second


def test_a_bare_decision_still_records_that_a_human_made_one() -> None:
    assert reviewed("", ResolutionUpdate(action="confirm")) == f"{REVIEW_NOTE_PREFIX}confirm"


def test_a_note_is_normalised_before_it_reaches_the_column() -> None:
    note = reviewed("", ResolutionUpdate(action="reject", note="two\x00lines\x1fhere"))

    assert "\x00" not in note and "\x1f" not in note
    assert "twolineshere" in note


def test_the_stored_clause_cannot_outgrow_the_reason_cap() -> None:
    """The model caps the field; this caps what is written, so neither end depends on the other."""
    note = reviewed("", ResolutionUpdate(action="confirm", note="n" * MAX_REASON_LENGTH))

    assert len(note) <= MAX_REASON_LENGTH + len(REVIEW_NOTE_PREFIX) + len("confirm - ")


# -- the query -------------------------------------------------------------------------------------


def _compiled(category_slug: str | None) -> str:
    statement = review_queue_statement(DEFAULT_REVIEW_STATES, category_slug, limit=A_PAGE, offset=0)
    return str(statement.compile(dialect=postgresql.dialect()))


def test_the_queue_is_ordered_worst_first_and_totally() -> None:
    compiled = " ".join(_compiled(None).split())

    assert "ORDER BY curated_entry.resolution_confidence ASC NULLS FIRST" in compiled
    # Without these two the order of equally-confident rows is whatever the plan happened to produce,
    # which makes a paged listing able to show one row twice and another never.
    assert "category.slug, curated_entry.position" in compiled


def test_the_queue_predicate_mirrors_the_partial_index_it_is_meant_to_scan() -> None:
    compiled = " ".join(_compiled(None).split())

    assert "curated_entry.removed_at IS NULL" in compiled
    assert "curated_entry.resolution_state IN" in compiled
    assert DEFAULT_REVIEW_STATES == (ResolutionState.UNRESOLVED, ResolutionState.AUTO)


def test_a_retired_workbooks_rows_are_excluded_by_the_query_itself() -> None:
    """Asserted on the compiled SQL as well as against a real Postgres, because the database test skips
    on a workstation with none and this predicate is the kind that is quietly dropped in a refactor."""
    for compiled in (" ".join(_compiled(None).split()), " ".join(_compiled("marvel").split())):
        assert "category.retired_at IS NULL" in compiled


def test_naming_a_category_scopes_the_queue_and_omitting_one_does_not() -> None:
    scoped = " ".join(_compiled("marvel").split())
    everything = " ".join(_compiled(None).split())

    assert "category.slug = " in scoped
    assert "category.slug = " not in everything


def test_the_queue_pages_in_the_database_not_in_python() -> None:
    compiled = " ".join(_compiled(None).split())

    assert "LIMIT" in compiled and "OFFSET" in compiled
