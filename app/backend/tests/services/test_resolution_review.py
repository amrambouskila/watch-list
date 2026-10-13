"""The review queue's state machine, against a real Postgres.

Two halves, and the second is the point of the task. The first is what each action writes; the second is
how that composes with the next ingest pass - `needs_resolution` is imported from the reconciler itself
rather than restated here, because a copy of its rule could agree with this file and disagree with the
loop that actually runs (master plan 6.5 rule 5, CLAUDE.md 18.2).

Provider traffic is recorded fixtures through an `httpx.MockTransport`. Nothing here reaches a network.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Final

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from provider_fixtures import TMDB, fixture_response
from review_support import (
    ABSOLUTE,
    AIRED,
    ONE_PIECE_TMDB_ID,
    seeded_category,
    seeded_entry,
    seeded_episodes,
    seeded_numbering,
    seeded_title,
    tmdb_runtime,
)
from tv_watchlist.clock import utcnow
from tv_watchlist.config import Settings
from tv_watchlist.data.enums import MediaType, ResolutionState, UnitKind
from tv_watchlist.data.errors import EntryNotFoundError, ResolutionConflictError
from tv_watchlist.data.models import CuratedEntry, CuratedEntryItem
from tv_watchlist.ingest.reconciler import needs_resolution
from tv_watchlist.ingest.runtime import IngestRuntime
from tv_watchlist.models.resolution_update import ResolutionUpdate
from tv_watchlist.services import resolution_review
from tv_watchlist.services.catalog import Catalog

SPAN_START: Final[int] = 19
SPAN_END: Final[int] = 53
SPAN_LENGTH: Final[int] = SPAN_END - SPAN_START + 1
A_DVD_ORDER: Final[str] = "dvd"
AN_UNKNOWN_ID: Final[str] = "00000000-0000-4000-8000-000000000000"


@pytest.fixture
async def runtime(settings: Settings, catalog: Catalog, engine: AsyncEngine) -> AsyncIterator[IngestRuntime]:
    """A configured TMDB leg, answering One Piece's recorded series document and its external ids."""
    built = tmdb_runtime(
        settings,
        catalog,
        engine,
        fixture_response(TMDB, "tv_37854"),
        fixture_response(TMDB, "tv_37854_external_ids"),
    )
    yield built
    await built.aclose()


@pytest.fixture
async def unconfigured(settings: Settings, catalog: Catalog, engine: AsyncEngine) -> AsyncIterator[IngestRuntime]:
    built = tmdb_runtime(settings, catalog, engine, token=None)
    yield built
    await built.aclose()


async def _items(session: AsyncSession, entry: CuratedEntry) -> int:
    statement = select(func.count()).select_from(CuratedEntryItem).where(CuratedEntryItem.curated_entry_id == entry.id)
    return (await session.execute(statement)).scalar_one()


# -- what each action writes ------------------------------------------------------------------------


async def test_confirming_pins_the_entry_at_full_confidence(
    db_session: AsyncSession, settings: Settings, runtime: IngestRuntime
) -> None:
    category = await seeded_category(db_session, "confirm-pins")
    entry = await seeded_entry(db_session, category, position=1, state=ResolutionState.AUTO, confidence=Decimal("0.50"))

    read = await resolution_review.apply_resolution(
        db_session, settings, runtime, entry.id, ResolutionUpdate(action="confirm")
    )

    assert read.resolution_state is ResolutionState.CONFIRMED
    assert read.resolution_confidence == 1.0
    assert entry.resolution_confidence == Decimal("1.00")


async def test_a_confirmation_records_the_human_reason_on_the_row(
    db_session: AsyncSession, settings: Settings, runtime: IngestRuntime
) -> None:
    category = await seeded_category(db_session, "confirm-notes")
    entry = await seeded_entry(db_session, category, position=1, state=ResolutionState.AUTO, note="auto: 0.50 match")

    await resolution_review.apply_resolution(
        db_session, settings, runtime, entry.id, ResolutionUpdate(action="confirm", note="checked the box set")
    )

    assert "checked the box set" in entry.resolution_note
    # The resolver's own clause survives: a review note is added beside it, never instead of it.
    assert "auto: 0.50 match" in entry.resolution_note


async def test_a_note_carrying_control_characters_is_normalised_before_it_is_stored(
    db_session: AsyncSession, settings: Settings, runtime: IngestRuntime
) -> None:
    """A note is stored text, not a log line, but a NUL is still not something Postgres can hold."""
    category = await seeded_category(db_session, "confirm-sanitised")
    entry = await seeded_entry(db_session, category, position=1, state=ResolutionState.AUTO)

    await resolution_review.apply_resolution(
        db_session, settings, runtime, entry.id, ResolutionUpdate(action="confirm", note="two\x00lines\x1fhere")
    )

    assert "\x00" not in entry.resolution_note
    assert "\x1f" not in entry.resolution_note


async def test_correcting_repoints_the_entry_and_rebuilds_its_items(
    db_session: AsyncSession, settings: Settings, runtime: IngestRuntime
) -> None:
    category = await seeded_category(db_session, "correct-repoints")
    entry = await seeded_entry(db_session, category, position=1, raw_title="One Piece")
    title = await seeded_title(db_session, name="One Piece", tmdb_id=ONE_PIECE_TMDB_ID)
    await seeded_numbering(db_session, title, await seeded_episodes(db_session, title), order_type=ABSOLUTE)

    read = await resolution_review.apply_resolution(
        db_session,
        settings,
        runtime,
        entry.id,
        ResolutionUpdate(
            action="correct",
            media_type=MediaType.TV,
            tmdb_id=ONE_PIECE_TMDB_ID,
            unit_kind=UnitKind.EPISODES,
            order_type=ABSOLUTE,
            span_start=SPAN_START,
            span_end=SPAN_END,
        ),
    )

    assert read.resolution_state is ResolutionState.CONFIRMED
    assert read.title is not None and read.title.tmdb_id == ONE_PIECE_TMDB_ID
    assert await _items(db_session, entry) == SPAN_LENGTH


async def test_correcting_with_an_order_the_title_lacks_is_refused_and_writes_nothing(
    db_session: AsyncSession, settings: Settings, runtime: IngestRuntime
) -> None:
    category = await seeded_category(db_session, "correct-missing-order")
    entry = await seeded_entry(db_session, category, position=1, state=ResolutionState.AUTO)
    title = await seeded_title(db_session, name="One Piece", tmdb_id=ONE_PIECE_TMDB_ID)
    episodes = await seeded_episodes(db_session, title)
    await seeded_numbering(db_session, title, episodes, order_type=ABSOLUTE)
    await seeded_numbering(db_session, title, episodes, order_type=AIRED)

    with pytest.raises(ResolutionConflictError):
        await resolution_review.apply_resolution(
            db_session,
            settings,
            runtime,
            entry.id,
            ResolutionUpdate(
                action="correct", media_type=MediaType.TV, tmdb_id=ONE_PIECE_TMDB_ID, order_type=A_DVD_ORDER
            ),
        )

    assert entry.resolution_state is ResolutionState.AUTO
    assert entry.title_id is None


async def test_correcting_without_a_configured_provider_is_refused(
    db_session: AsyncSession, settings: Settings, unconfigured: IngestRuntime
) -> None:
    """An absent token is a disabled feature, and a review decision it cannot honour is a conflict."""
    category = await seeded_category(db_session, "correct-unconfigured")
    entry = await seeded_entry(db_session, category, position=1)

    with pytest.raises(ResolutionConflictError):
        await resolution_review.apply_resolution(
            db_session,
            settings=settings,
            runtime=unconfigured,
            entry_id=entry.id,
            update=ResolutionUpdate(action="correct", media_type=MediaType.TV, tmdb_id=ONE_PIECE_TMDB_ID),
        )

    assert entry.resolution_state is ResolutionState.UNRESOLVED


async def test_correcting_to_a_title_the_provider_has_nothing_for_is_refused(
    db_session: AsyncSession, settings: Settings, catalog: Catalog, engine: AsyncEngine
) -> None:
    """`ensure_title` answers `None` when TMDB 404s and nothing is stored: that is not a title."""
    category = await seeded_category(db_session, "correct-unknown-title")
    entry = await seeded_entry(db_session, category, position=1)
    built = tmdb_runtime(settings, catalog, engine)

    try:
        with pytest.raises(ResolutionConflictError):
            await resolution_review.apply_resolution(
                db_session,
                settings,
                built,
                entry.id,
                ResolutionUpdate(action="correct", media_type=MediaType.TV, tmdb_id=ONE_PIECE_TMDB_ID),
            )
    finally:
        await built.aclose()

    assert entry.title_id is None


async def test_rejecting_clears_the_title_and_the_items_but_keeps_the_row(
    db_session: AsyncSession, settings: Settings, runtime: IngestRuntime
) -> None:
    category = await seeded_category(db_session, "reject-clears")
    title = await seeded_title(db_session, name="A film that is not this row", tmdb_id=None)
    entry = await seeded_entry(
        db_session,
        category,
        position=1,
        state=ResolutionState.AUTO,
        confidence=Decimal("0.50"),
        unit_kind=UnitKind.MOVIE,
        title=title,
    )

    read = await resolution_review.apply_resolution(
        db_session, settings, runtime, entry.id, ResolutionUpdate(action="reject", note="a featurette, not a film")
    )

    assert read.resolution_state is ResolutionState.REJECTED
    assert read.title is None
    assert read.resolution_confidence is None
    assert (entry.span_start, entry.span_end, entry.order_type) == (None, None, None)
    assert await _items(db_session, entry) == 0
    # The row itself is untouched: position, sheet row and verbatim cells are the sheet's, not ours.
    assert read.position == 1
    assert read.cells == {"title": ""}


async def test_an_unknown_entry_is_refused(
    db_session: AsyncSession, settings: Settings, runtime: IngestRuntime
) -> None:
    with pytest.raises(EntryNotFoundError):
        await resolution_review.apply_resolution(
            db_session, settings, runtime, uuid.UUID(AN_UNKNOWN_ID), ResolutionUpdate(action="confirm")
        )


# -- how the decisions compose with the next ingest pass ---------------------------------------------


async def test_the_next_ingest_never_re_resolves_a_confirmed_entry(
    db_session: AsyncSession, settings: Settings, runtime: IngestRuntime
) -> None:
    """Rule 5, asserted against the reconciler's own predicate rather than a restatement of it."""
    category = await seeded_category(db_session, "confirm-survives")
    entry = await seeded_entry(db_session, category, position=1, state=ResolutionState.AUTO, confidence=Decimal("0.50"))

    await resolution_review.apply_resolution(
        db_session, settings, runtime, entry.id, ResolutionUpdate(action="confirm")
    )

    assert needs_resolution(entry.resolution_state, is_new=False, raws_changed=False) is False
    # The one thing that does bring it back: the cells the human decided about moved.
    assert needs_resolution(entry.resolution_state, is_new=False, raws_changed=True) is True


async def test_a_rejected_entry_is_left_alone_until_its_cells_move(
    db_session: AsyncSession, settings: Settings, runtime: IngestRuntime
) -> None:
    category = await seeded_category(db_session, "reject-survives")
    entry = await seeded_entry(db_session, category, position=1, state=ResolutionState.AUTO)

    await resolution_review.apply_resolution(db_session, settings, runtime, entry.id, ResolutionUpdate(action="reject"))

    assert needs_resolution(entry.resolution_state, is_new=False, raws_changed=False) is False
    assert needs_resolution(entry.resolution_state, is_new=False, raws_changed=True) is True


# -- the queue itself -------------------------------------------------------------------------------


async def test_the_queue_is_worst_first_and_excludes_settled_rows(db_session: AsyncSession, settings: Settings) -> None:
    category = await seeded_category(db_session, "queue-order")
    await seeded_entry(db_session, category, position=1, state=ResolutionState.AUTO, confidence=Decimal("0.80"))
    await seeded_entry(db_session, category, position=2, state=ResolutionState.UNRESOLVED)
    await seeded_entry(db_session, category, position=3, state=ResolutionState.AUTO, confidence=Decimal("0.50"))
    await seeded_entry(db_session, category, position=4, state=ResolutionState.CONFIRMED, confidence=Decimal("1.00"))
    await seeded_entry(db_session, category, position=5, state=ResolutionState.REJECTED)

    queue = await resolution_review.list_for_review(db_session, settings, category_slug=category.slug)

    assert [entry.position for entry in queue] == [2, 3, 1]


async def test_the_queue_is_filterable_by_category_and_state(db_session: AsyncSession, settings: Settings) -> None:
    first = await seeded_category(db_session, "queue-first")
    second = await seeded_category(db_session, "queue-second")
    await seeded_entry(db_session, first, position=1, state=ResolutionState.UNRESOLVED)
    await seeded_entry(db_session, first, position=2, state=ResolutionState.AUTO, confidence=Decimal("0.65"))
    await seeded_entry(db_session, second, position=1, state=ResolutionState.UNRESOLVED)

    scoped = await resolution_review.list_for_review(db_session, settings, category_slug=first.slug)
    only_auto = await resolution_review.list_for_review(
        db_session, settings, states=(ResolutionState.AUTO,), category_slug=first.slug
    )

    assert [entry.position for entry in scoped] == [1, 2]
    assert [entry.resolution_state for entry in only_auto] == [ResolutionState.AUTO]


async def test_a_soft_deleted_entry_never_reaches_the_queue(db_session: AsyncSession, settings: Settings) -> None:
    category = await seeded_category(db_session, "queue-soft-deleted")
    removed = await seeded_entry(db_session, category, position=1, state=ResolutionState.UNRESOLVED)
    removed.removed_at = utcnow()
    await db_session.flush()

    queue = await resolution_review.list_for_review(db_session, settings, category_slug=category.slug)

    assert queue == []


async def test_a_retired_categorys_rows_never_reach_the_queue(db_session: AsyncSession, settings: Settings) -> None:
    """Retiring a workbook keeps its rows - the curated chain is soft-deleted, never purged (5.13).

    They are still real entries with real history, so they stay in the table; what they are not is work
    a human should be asked to do. A queue that listed them would ask about a file the owner has put away.
    """
    live = await seeded_category(db_session, "queue-live-category")
    retired = await seeded_category(db_session, "queue-retired-category")
    retired.retired_at = utcnow()
    standing = await seeded_entry(db_session, live, position=1, state=ResolutionState.UNRESOLVED)
    # Confidence 0.10 would sort this one to the very front of the queue if it were listed at all.
    await seeded_entry(db_session, retired, position=1, state=ResolutionState.AUTO, confidence=Decimal("0.10"))
    await seeded_entry(db_session, retired, position=2, state=ResolutionState.UNRESOLVED)
    await db_session.flush()

    queue = await resolution_review.list_for_review(db_session, settings)
    scoped = await resolution_review.list_for_review(db_session, settings, category_slug=retired.slug)

    # The live category's row, and only it: retiring one workbook empties that workbook, not the queue.
    assert [entry.id for entry in queue] == [standing.id]
    assert scoped == []


async def test_the_queue_pages(db_session: AsyncSession, settings: Settings) -> None:
    category = await seeded_category(db_session, "queue-pages")
    for position in range(1, 5):
        await seeded_entry(
            db_session, category, position=position, state=ResolutionState.AUTO, confidence=Decimal(f"0.{position}0")
        )

    page = await resolution_review.list_for_review(db_session, settings, category_slug=category.slug, limit=2, offset=1)

    assert [entry.position for entry in page] == [2, 3]


async def test_a_confirmed_entry_leaves_the_queue(
    db_session: AsyncSession, runtime: IngestRuntime, settings: Settings
) -> None:
    category = await seeded_category(db_session, "queue-after-confirm")
    entry = await seeded_entry(db_session, category, position=1, state=ResolutionState.AUTO, confidence=Decimal("0.50"))

    await resolution_review.apply_resolution(
        db_session, settings, runtime, entry.id, ResolutionUpdate(action="confirm")
    )
    queue = await resolution_review.list_for_review(db_session, settings, category_slug=category.slug)

    assert queue == []
