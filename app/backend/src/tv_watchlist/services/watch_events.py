"""Recording one watch fact, and reading the progress it derives.

`watch_event` is append-only - the `watch_event_no_mutation` trigger (revision 0001) rejects every
UPDATE and DELETE, and nothing here issues one. A status is never corrected in place: a correction is
another INSERT, and the two `DISTINCT ON` views collapse the log into a current state at read time
(CLAUDE.md section 5.14, section 11.2 rule 12).

Three things are the server's, never the body's:

- **`tmdb_key`.** It is the log's own identity, and the only pointer that survives a full metadata
  rebuild, so it is derived from the subject row rather than accepted from a caller (section 5.13).
- **`source`.** `ui` from this route; the Phase 3 player passes `player` through the same service.
  Never `jellyfin` - the position comes from the browser, only the bytes come from the server.
- **`recorded_at`.** Server-assigned, so that two events carrying the same client stamp still order
  deterministically.

`category_id` on the body is a **selector, not a value**: one playable unit can sit in several curated
orders, and it names which of them the caller means. What lands in the row is always a category read
back off a row this service resolved, so an id nothing answers to can never reach a foreign key.

Progress is written to BOTH stores (section 0.2). The durable half is the row appended here; the lossy
four-value half is the sheet cell `watch_mirror` projects onto, scheduled after the commit and never
awaited on the request path - it opens a workbook, and a watch event must not wait on Excel.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Final

from sqlalchemy import ColumnElement, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tv_watchlist.clock import utcnow
from tv_watchlist.data.enums import MediaType, WatchEventSource, WatchSubjectKind
from tv_watchlist.data.errors import EntryNotFoundError, WatchSubjectNotFoundError
from tv_watchlist.data.models import Category, CuratedEntry, CuratedEntryItem, Episode, Title, WatchEvent
from tv_watchlist.models.entry_progress import EntryProgress
from tv_watchlist.models.watch_event_create import WatchEventCreate
from tv_watchlist.models.watch_event_read import WatchEventRead
from tv_watchlist.services import watch_mirror
from tv_watchlist.services.catalog import Catalog
from tv_watchlist.services.entries import WATCH_STATE, select_watch_state
from tv_watchlist.services.mirror_outcome import DEFERRED, MirrorOutcome
from tv_watchlist.services.tmdb_key import tmdb_key
from tv_watchlist.workbook.errors import WorkbookError

_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)
_JOB: Final[str] = "watch_event"


@dataclass(frozen=True)
class _Subject:
    """What one resolved subject contributes to the row, and which entry it moves.

    Tightly coupled to this module and used nowhere else, which is the one exception the file-per-concept
    rule allows (CLAUDE.md section 7). Exactly one of the three ids is set, because `one_subject` is a
    database CHECK: `entry_id` is the entry whose progress changes, which for an episode or a film is the
    queue slot holding it rather than a column the row could carry.
    """

    episode_id: uuid.UUID | None = None
    title_id: uuid.UUID | None = None
    curated_entry_id: uuid.UUID | None = None
    tmdb_key: str | None = None
    entry_id: uuid.UUID | None = None
    category_id: uuid.UUID | None = None


async def record_watch_event(
    session: AsyncSession,
    body: WatchEventCreate,
    *,
    source: WatchEventSource = WatchEventSource.UI,
    playback_entry: CuratedEntry | None = None,
    clock: Callable[[], datetime] = utcnow,
) -> WatchEventRead:
    """Append one watch fact, and read back the progress it derives.

    The subject is resolved before anything is written, so an id nothing answers to is a
    `WatchSubjectNotFoundError` - a 404 the caller can act on - rather than the integrity error the
    `one_subject` CHECK would raise on the insert.
    """
    subject = await _subject(session, body)
    if playback_entry is not None:
        subject = replace(subject, entry_id=playback_entry.id, category_id=playback_entry.category_id)
    event = WatchEvent(
        occurred_at=_occurred(body.occurred_at, clock),
        subject_kind=body.subject_kind,
        kind=body.kind,
        source=source,
        tmdb_key=subject.tmdb_key,
        episode_id=subject.episode_id,
        title_id=subject.title_id,
        curated_entry_id=subject.curated_entry_id,
        category_id=subject.category_id,
        position_seconds=body.position_seconds,
        runtime_seconds=body.runtime_seconds,
        device=body.device,
        note=body.note,
    )
    session.add(event)
    # Flushed here rather than left to the commit: the row's server-assigned `recorded_at` and the view
    # the progress below reads both need the INSERT to have happened.
    await session.flush()
    progress = None if subject.entry_id is None else await entry_progress(session, subject.entry_id)
    _LOGGER.info(
        "watch_event_recorded job=%s kind=%s subject_kind=%s source=%s entry=%s",
        _JOB,
        body.kind.value,
        body.subject_kind.value,
        source.value,
        subject.entry_id,
    )
    return _read(event, subject, progress)


async def entry_progress(
    session: AsyncSession, entry_id: uuid.UUID, *, category_slug: str | None = None
) -> EntryProgress:
    """One entry's derived state, straight off `curated_entry_watch_state`.

    The view's own WHERE is `removed_at IS NULL`, so a missing row IS the 404: no live entry carries
    that id, and no second existence query is needed to say so. `category_slug` narrows the lookup to
    one workbook, so a nested route cannot answer for an entry of a category its path does not name.
    """
    # The session is autoflush=False, so events a caller has only staged would otherwise be invisible
    # to the view - and a state that ignored them would contradict the same transaction.
    await session.flush()
    statement = select_watch_state().where(WATCH_STATE.c.curated_entry_id == entry_id)
    if category_slug is not None:
        statement = (
            statement.join(CuratedEntry, CuratedEntry.id == WATCH_STATE.c.curated_entry_id)
            .join(Category, Category.id == CuratedEntry.category_id)
            .where(Category.slug == category_slug)
        )
    found = (await session.execute(statement)).first()
    if found is None:
        raise EntryNotFoundError(str(entry_id))
    return EntryProgress.model_validate(found)


async def mirror_recorded_entry(
    session_factory: async_sessionmaker[AsyncSession],
    catalog: Catalog,
    entry_id: uuid.UUID,
    *,
    clock: Callable[[], datetime] = utcnow,
) -> MirrorOutcome:
    """The scheduled half of "progress is written to both": one entry's status onto its own sheet row.

    Takes a factory rather than a session because it runs as a background task, and a background task
    outlives the request whose session it would otherwise borrow. A workbook refusal is the mirror
    losing, which is the ordering it is supposed to lose in: neither store moves, and the identical
    diff replays on the next pass. Nothing here can fail the response - it has already been sent.
    """
    async with session_factory() as session:
        try:
            outcome = await watch_mirror.mirror_entry(session, catalog, entry_id, clock=clock)
            await session.commit()
        except WorkbookError as error:
            # The expected refusal: Excel holds the file, or the sheet moved under the plan. Quiet,
            # because it is the mirror losing the race it is supposed to lose.
            _LOGGER.warning("watch_event_mirror_failed job=%s entry=%s error=%s", _JOB, entry_id, type(error).__name__)
            return DEFERRED
        except Exception:  # noqa: BLE001 - a fire-and-forget task must not escape unlogged
            # Anything else - a lost connection, a pool reset, a commit that fails - would otherwise
            # surface as an ASGI traceback with no request left to carry it. The commit sits inside the
            # try for exactly that reason: it is the statement most likely to be the one that fails.
            _LOGGER.exception("watch_event_mirror_crashed job=%s entry=%s", _JOB, entry_id)
            return DEFERRED
        return outcome


async def _subject(session: AsyncSession, body: WatchEventCreate) -> _Subject:
    if body.subject_kind is WatchSubjectKind.EPISODE:
        return await _episode_subject(session, body.subject_id, body.category_id)
    if body.subject_kind is WatchSubjectKind.TITLE:
        return await _title_subject(session, body.subject_id, body.category_id)
    return await _entry_subject(session, body.subject_id)


async def _episode_subject(session: AsyncSession, episode_id: uuid.UUID, category_id: uuid.UUID | None) -> _Subject:
    """An episode, keyed by its own bucketed `(season_number, episode_number)` - never a human SxxEyy."""
    found = (
        await session.execute(
            select(
                Episode.id,
                Episode.season_number,
                Episode.episode_number,
                Title.media_type,
                Title.tmdb_id,
            )
            .join(Title, Title.id == Episode.title_id)
            .where(Episode.id == episode_id)
        )
    ).first()
    if found is None:
        raise WatchSubjectNotFoundError(_named(WatchSubjectKind.EPISODE, episode_id))
    holder = await _holder(session, CuratedEntryItem.episode_id == episode_id, category_id)
    return _Subject(
        episode_id=found.id,
        tmdb_key=_episode_key(found.media_type, found.tmdb_id, found.season_number, found.episode_number),
        entry_id=None if holder is None else holder[0],
        category_id=None if holder is None else holder[1],
    )


async def _title_subject(session: AsyncSession, title_id: uuid.UUID, category_id: uuid.UUID | None) -> _Subject:
    """A whole work, which for a film is the playable unit and for a series is a coarse fact about it."""
    found = (
        await session.execute(select(Title.id, Title.media_type, Title.tmdb_id).where(Title.id == title_id))
    ).first()
    if found is None:
        raise WatchSubjectNotFoundError(_named(WatchSubjectKind.TITLE, title_id))
    holder = await _holder(session, CuratedEntryItem.movie_title_id == title_id, category_id)
    return _Subject(
        title_id=found.id,
        tmdb_key=_work_key(found.media_type, found.tmdb_id),
        entry_id=None if holder is None else holder[0],
        category_id=None if holder is None else holder[1],
    )


async def _entry_subject(session: AsyncSession, entry_id: uuid.UUID) -> _Subject:
    """One curated row. Its own category is read off the row, never taken from the body."""
    found = (
        await session.execute(
            select(CuratedEntry.id, CuratedEntry.category_id, Title.media_type, Title.tmdb_id)
            .outerjoin(Title, Title.id == CuratedEntry.title_id)
            .where(CuratedEntry.id == entry_id, CuratedEntry.removed_at.is_(None))
        )
    ).first()
    if found is None:
        raise WatchSubjectNotFoundError(_named(WatchSubjectKind.CURATED_ENTRY, entry_id))
    return _Subject(
        curated_entry_id=found.id,
        tmdb_key=_work_key(found.media_type, found.tmdb_id),
        entry_id=found.id,
        category_id=found.category_id,
    )


async def _holder(
    session: AsyncSession, subject: ColumnElement[bool], category_id: uuid.UUID | None
) -> tuple[uuid.UUID, uuid.UUID] | None:
    """The live queue slot holding this playable unit, as `(curated_entry_id, category_id)`.

    `curated_entry_item` is the flattened queue, so this is one indexed lookup rather than a span scan.
    When the body named a category the search stays inside it and answers nothing if that category does
    not hold the unit - a caller that named a category meant it. Otherwise the first category by name,
    and its lowest queue slot, wins - deterministically, so the same event twice moves the same entry.
    """
    statement = (
        select(CuratedEntryItem.curated_entry_id, CuratedEntryItem.category_id)
        .join(CuratedEntry, CuratedEntry.id == CuratedEntryItem.curated_entry_id)
        .join(Category, Category.id == CuratedEntry.category_id)
        .where(subject, CuratedEntry.removed_at.is_(None))
        # By the category's own name rather than its UUID, so "the lowest queue slot wins" is a rule a
        # reader can predict from the library rather than from whichever id the database happened to mint.
        .order_by(Category.slug, CuratedEntryItem.absolute_position)
        .limit(1)
    )
    if category_id is not None:
        statement = statement.where(CuratedEntryItem.category_id == category_id)
    found = (await session.execute(statement)).first()
    return None if found is None else (found.curated_entry_id, found.category_id)


def _episode_key(media_type: MediaType, tmdb_id: int | None, season_number: int, episode_number: int) -> str | None:
    """`tv:37854:s2:e62`. None when the title carries no provider match, which is a first-class state."""
    if tmdb_id is None:
        return None
    return tmdb_key(media_type, tmdb_id, season_number=season_number, episode_number=episode_number)


def _work_key(media_type: MediaType | None, tmdb_id: int | None) -> str | None:
    """`movie:603`. None for an entry the resolver has not matched, or a title with no provider id."""
    if media_type is None or tmdb_id is None:
        return None
    return tmdb_key(media_type, tmdb_id)


def _occurred(stamp: datetime | None, clock: Callable[[], datetime]) -> datetime:
    """The client's stamp, or now.

    A naive one is read as UTC at the boundary: the column is `timestamptz`, every other stamp in this
    schema is aware, and asyncpg would otherwise be handed a value it has to guess a zone for.
    """
    if stamp is None:
        return clock()
    return stamp if stamp.tzinfo is not None else stamp.replace(tzinfo=UTC)


def _named(kind: WatchSubjectKind, subject_id: uuid.UUID) -> str:
    """What the 404 message says was not there: "No episode <id> to record a watch event against."."""
    return f"{kind.value} {subject_id}"


def _read(event: WatchEvent, subject: _Subject, progress: EntryProgress | None) -> WatchEventRead:
    """The wire shape. Listed by hand so every attribute that crosses the boundary is visible at one site."""
    return WatchEventRead.model_validate(
        {
            "id": event.id,
            "occurred_at": event.occurred_at,
            "recorded_at": event.recorded_at,
            "subject_kind": event.subject_kind,
            "kind": event.kind,
            "source": event.source,
            "tmdb_key": event.tmdb_key,
            # The entry this event MOVES, which the stored row can only carry for a curated_entry
            # subject: `one_subject` allows exactly one typed id, so an episode's holder travels here.
            "curated_entry_id": subject.entry_id,
            "category_id": event.category_id,
            "position_seconds": event.position_seconds,
            "runtime_seconds": event.runtime_seconds,
            "progress": progress,
        }
    )
