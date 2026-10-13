"""The append-only guarantee: watch_event refuses every mutation, and the database is what refuses it."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tv_watchlist.data.enums import ResolutionState, UnitKind, WatchEventKind, WatchEventSource, WatchSubjectKind
from tv_watchlist.data.models import Category, CuratedEntry, WatchEvent


async def _one_event(db_session: AsyncSession) -> WatchEvent:
    category = Category(slug=f"probe-{uuid.uuid4().hex}", file_name="Probe.xlsx", sheet_title="Probe", accent="#1F2937")
    db_session.add(category)
    await db_session.flush()
    entry = CuratedEntry(
        category_id=category.id,
        position=1,
        unit_kind=UnitKind.UNKNOWN,
        resolution_state=ResolutionState.UNRESOLVED,
        raw_cells={"Title": "Probe"},
    )
    db_session.add(entry)
    await db_session.flush()
    event = WatchEvent(
        occurred_at=datetime.now(UTC),
        subject_kind=WatchSubjectKind.CURATED_ENTRY,
        kind=WatchEventKind.COMPLETED,
        source=WatchEventSource.UI,
        curated_entry_id=entry.id,
        category_id=category.id,
    )
    db_session.add(event)
    await db_session.flush()
    return event


async def test_an_update_against_watch_event_is_refused_by_the_database(db_session: AsyncSession) -> None:
    event = await _one_event(db_session)
    with pytest.raises(IntegrityError, match="append-only"):
        await db_session.execute(update(WatchEvent).where(WatchEvent.id == event.id).values(note="rewritten"))


async def test_a_delete_against_watch_event_is_refused_by_the_database(db_session: AsyncSession) -> None:
    event = await _one_event(db_session)
    with pytest.raises(IntegrityError, match="append-only"):
        await db_session.execute(delete(WatchEvent).where(WatchEvent.id == event.id))


async def test_a_progressed_event_without_a_position_is_refused(db_session: AsyncSession) -> None:
    event = await _one_event(db_session)
    db_session.add(
        WatchEvent(
            occurred_at=datetime.now(UTC),
            subject_kind=WatchSubjectKind.CURATED_ENTRY,
            kind=WatchEventKind.PROGRESSED,
            source=WatchEventSource.PLAYER,
            curated_entry_id=event.curated_entry_id,
            category_id=event.category_id,
        )
    )
    # Only the flush can raise: add() just stages the instance in the session's identity map.
    with pytest.raises(IntegrityError, match="progressed_has_position"):
        await db_session.flush()
