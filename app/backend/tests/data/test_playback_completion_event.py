from __future__ import annotations

import uuid

import pytest
from sqlalchemy import UniqueConstraint, delete, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from playback_completion_support import completion_row
from tv_watchlist.data.models import PlaybackCompletionEvent


async def test_membership_keeps_exact_selected_event(db_session: AsyncSession) -> None:
    receipt = await completion_row(db_session)
    member = PlaybackCompletionEvent(completion_id=receipt.id, watch_event_id=receipt.selected_watch_event_id)
    db_session.add(member)
    await db_session.flush()
    identifier = member.id
    db_session.expunge(member)
    stored = await db_session.get(PlaybackCompletionEvent, identifier)
    assert stored.completion_id == receipt.id
    assert stored.watch_event_id == receipt.selected_watch_event_id
    assert {"created_at", "updated_at"}.isdisjoint(PlaybackCompletionEvent.__table__.columns.keys())


@pytest.mark.parametrize("operation", ["update", "delete"])
async def test_membership_is_immutable_in_postgres(db_session: AsyncSession, operation: str) -> None:
    receipt = await completion_row(db_session)
    member = PlaybackCompletionEvent(completion_id=receipt.id, watch_event_id=receipt.selected_watch_event_id)
    db_session.add(member)
    await db_session.flush()
    mutation = (
        update(PlaybackCompletionEvent).values(completion_id=receipt.id)
        if operation == "update"
        else delete(PlaybackCompletionEvent)
    )
    with pytest.raises(IntegrityError, match="append-only") as caught:
        async with db_session.begin_nested():
            await db_session.execute(mutation.where(PlaybackCompletionEvent.id == member.id))
    assert caught.value.orig.sqlstate == "23001"


@pytest.mark.parametrize("same_receipt", [False, True])
async def test_an_event_cannot_belong_to_two_memberships(db_session: AsyncSession, same_receipt: bool) -> None:
    first, second = await completion_row(db_session), await completion_row(db_session)
    db_session.add(PlaybackCompletionEvent(completion_id=first.id, watch_event_id=first.selected_watch_event_id))
    await db_session.flush()
    with pytest.raises(IntegrityError, match="uq_playback_completion_event_"):
        async with db_session.begin_nested():
            db_session.add(
                PlaybackCompletionEvent(
                    completion_id=first.id if same_receipt else second.id, watch_event_id=first.selected_watch_event_id
                )
            )
            await db_session.flush()


@pytest.mark.parametrize("field", ["completion_id", "watch_event_id"])
async def test_membership_foreign_keys_require_existing_history(db_session: AsyncSession, field: str) -> None:
    receipt = await completion_row(db_session)
    values = {"completion_id": receipt.id, "watch_event_id": receipt.selected_watch_event_id}
    values[field] = uuid.uuid4()
    with pytest.raises(IntegrityError, match=f"fk_playback_completion_event_{field}"):
        async with db_session.begin_nested():
            db_session.add(PlaybackCompletionEvent(**values))
            await db_session.flush()


def test_membership_has_the_named_pair_and_event_uniques() -> None:
    uniques = {
        tuple(column.name for column in constraint.columns)
        for constraint in PlaybackCompletionEvent.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert uniques == {("watch_event_id",), ("completion_id", "watch_event_id")}
