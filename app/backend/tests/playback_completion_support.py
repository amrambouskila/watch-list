"""Real database fixtures for immutable file-completion evidence."""

from __future__ import annotations

import uuid

from episode_join_support import a_category, a_film, an_entry
from sqlalchemy.ext.asyncio import AsyncSession

from tv_watchlist.clock import utcnow
from tv_watchlist.data.enums import UnitKind, WatchEventKind, WatchEventSource, WatchSubjectKind
from tv_watchlist.data.models import PlaybackCompletion, WatchEvent


async def completed_event(session: AsyncSession, category_id: uuid.UUID, title_id: uuid.UUID) -> WatchEvent:
    event = WatchEvent(
        occurred_at=utcnow(),
        subject_kind=WatchSubjectKind.TITLE,
        kind=WatchEventKind.COMPLETED,
        source=WatchEventSource.PLAYER,
        title_id=title_id,
        category_id=category_id,
    )
    session.add(event)
    await session.flush()
    return event


async def completion_row(session: AsyncSession, **overrides: object) -> PlaybackCompletion:
    category = await a_category(session, f"receipt-{uuid.uuid4().hex}")
    title = await a_film(session, "Completion reference film")
    entry = await an_entry(session, category, title_id=title.id, unit_kind=UnitKind.MOVIE)
    event = await completed_event(session, category.id, title.id)
    fields: dict[str, object] = {
        "selected_watch_event_id": event.id,
        "category_id": category.id,
        "source_entry_id": entry.id,
        "jellyfin_item_id_snapshot": uuid.uuid4(),
        "jellyfin_id_snapshot": "0f1e2d3c4b5a69788796a5b4c3d20001",
        "queue_fingerprint": "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
        "occurrence_snapshot": [
            {
                "entry_id": str(entry.id),
                "subject_kind": "title",
                "subject_id_snapshot": str(title.id),
                "tmdb_key": None,
                "position_in_entry": 1,
            }
        ],
    }
    fields.update(overrides)
    receipt = PlaybackCompletion(**fields)
    session.add(receipt)
    await session.flush()
    return receipt
