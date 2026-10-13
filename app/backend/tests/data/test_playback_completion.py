from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from playback_completion_support import completion_row
from tv_watchlist.data.enums import JellyfinItemKind
from tv_watchlist.data.models import CuratedEntry, JellyfinItem, PlaybackCompletion


async def test_receipt_round_trips_exact_snapshot_and_server_default(db_session: AsyncSession) -> None:
    receipt = await completion_row(db_session)
    expected = receipt.occurrence_snapshot
    identifier = receipt.id
    db_session.expunge(receipt)
    stored = await db_session.get(PlaybackCompletion, identifier)
    assert stored.occurrence_snapshot == expected
    assert stored.order_type is None and stored.order_label == ""
    assert stored.queue_fingerprint == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert {"created_at", "updated_at"}.isdisjoint(PlaybackCompletion.__table__.columns.keys())


@pytest.mark.parametrize(
    "fields",
    [
        {"jellyfin_id_snapshot": ""},
        {"jellyfin_id_snapshot": "  "},
        {"queue_fingerprint": "a"},
        {"queue_fingerprint": "A" * 64},
        {"queue_fingerprint": "g" * 64},
        {"occurrence_snapshot": {}},
        {"occurrence_snapshot": None},
        {"order_label": "movie cannot carry numbering"},
        {"parent_index_number": 0},
        {"index_number": 1},
        {"index_number_end": 2},
        {"order_type": ""},
        {"order_type": " "},
        {"order_type": "aired"},
        {"order_type": "aired", "parent_index_number": 1},
        {"order_type": "aired", "index_number": 1},
        {"order_type": "aired", "parent_index_number": -1, "index_number": 1},
        {"order_type": "aired", "parent_index_number": 1, "index_number": -1},
        {"order_type": "aired", "parent_index_number": 1, "index_number": 1, "index_number_end": -1},
        {"order_type": "aired", "parent_index_number": 1, "index_number": 2, "index_number_end": 1},
    ],
)
async def test_database_refuses_malformed_receipt_shape(db_session: AsyncSession, fields: dict[str, object]) -> None:
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await completion_row(db_session, **fields)


@pytest.mark.parametrize("end", [None, 0, 3])
async def test_episode_receipt_preserves_open_order_vocabulary_and_zero_indices(
    db_session: AsyncSession, end: int | None
) -> None:
    receipt = await completion_row(
        db_session, order_type="provider-future-order", parent_index_number=0, index_number=0, index_number_end=end
    )
    assert receipt.order_type == "provider-future-order"
    assert receipt.index_number_end == end


@pytest.mark.parametrize("operation", ["update", "delete"])
async def test_receipt_is_immutable_in_postgres(db_session: AsyncSession, operation: str) -> None:
    receipt = await completion_row(db_session)
    mutation = (
        update(PlaybackCompletion).values(order_label="changed")
        if operation == "update"
        else delete(PlaybackCompletion)
    )
    with pytest.raises(IntegrityError, match="append-only") as caught:
        async with db_session.begin_nested():
            await db_session.execute(mutation.where(PlaybackCompletion.id == receipt.id))
    assert caught.value.orig.sqlstate == "23001"


async def test_selected_event_has_exactly_one_receipt(db_session: AsyncSession) -> None:
    receipt = await completion_row(db_session)
    with pytest.raises(IntegrityError, match="selected_watch_event_id"):
        async with db_session.begin_nested():
            await completion_row(db_session, selected_watch_event_id=receipt.selected_watch_event_id)


@pytest.mark.parametrize("field", ["selected_watch_event_id", "category_id", "source_entry_id"])
async def test_receipt_foreign_keys_require_retained_rows(db_session: AsyncSession, field: str) -> None:
    with pytest.raises(IntegrityError, match=f"fk_playback_completion_{field}"):
        async with db_session.begin_nested():
            await completion_row(db_session, **{field: uuid.uuid4()})


async def test_source_entry_cannot_be_deleted(db_session: AsyncSession) -> None:
    receipt = await completion_row(db_session)
    with pytest.raises(IntegrityError, match="fk_playback_completion_source_entry_id"):
        async with db_session.begin_nested():
            await db_session.execute(delete(CuratedEntry).where(CuratedEntry.id == receipt.source_entry_id))


async def test_receipt_does_not_depend_on_disposable_jellyfin_index(db_session: AsyncSession) -> None:
    item = JellyfinItem(jellyfin_id=uuid.uuid4().hex, kind=JellyfinItemKind.MOVIE, name="Snapshot reference")
    db_session.add(item)
    await db_session.flush()
    identifier, provider_id = item.id, item.jellyfin_id
    receipt = await completion_row(db_session, jellyfin_item_id_snapshot=identifier, jellyfin_id_snapshot=provider_id)
    await db_session.execute(delete(JellyfinItem).where(JellyfinItem.id == identifier))
    stored = await db_session.scalar(select(PlaybackCompletion).where(PlaybackCompletion.id == receipt.id))
    assert (stored.jellyfin_item_id_snapshot, stored.jellyfin_id_snapshot) == (identifier, provider_id)


async def test_raw_insert_has_empty_numbering_label(db_session: AsyncSession) -> None:
    receipt = await completion_row(db_session)
    from playback_completion_support import completed_event
    from tv_watchlist.data.models import WatchEvent

    event = await db_session.get(WatchEvent, receipt.selected_watch_event_id)
    replacement = await completed_event(db_session, receipt.category_id, event.title_id)
    result = await db_session.execute(
        text(
            "INSERT INTO playback_completion (selected_watch_event_id, category_id, source_entry_id,"
            " jellyfin_item_id_snapshot, jellyfin_id_snapshot, queue_fingerprint, occurrence_snapshot)"
            " SELECT :event_id, category_id, source_entry_id, jellyfin_item_id_snapshot, jellyfin_id_snapshot,"
            " queue_fingerprint, occurrence_snapshot FROM playback_completion WHERE id = :receipt_id"
            " RETURNING order_label"
        ),
        {"event_id": replacement.id, "receipt_id": receipt.id},
    )
    assert result.scalar_one() == ""
