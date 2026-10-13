"""`episode_order`: the aired rank this app computes, and every ordering TheTVDB offers at runtime.

Four rules shape every line here.

**A rank, not a number.** `sequence` is a dense 1-based rank within ONE numbering, and that single
choice is what makes every numbering one kind of object: a hand-written span like One Piece's `E19-53`
becomes one range scan (CLAUDE.md section 11.2, rule 10). What the UI prints is `order_season_number` /
`order_episode_number`, which travel beside the rank and are never computed from it.

**Season 0 is excluded from the aired walk and given its own numbering.** Without that exclusion an
anime's forty specials shift its whole main run. They are not dropped: they become a second ordering,
told apart from a provider ordering of the same type by `SPECIALS_ORDER_LABEL`. That exclusion applies
to the aired walk alone: a *provider* ordering is ranked exactly as the service listed it, specials in
place, so `sequence == 1` there is the ordering's first entry and not necessarily its first regular
episode - anything a reader sees comes from `order_season_number` / `order_episode_number`.

**The ordering names are data.** TheTVDB documents its season types as examples rather than an enum, so
the list is read at runtime and no name appears in this module - a test asserts that. A type this app
has never seen is written like any other. The one name refused is the one this app computes itself:
writing a provider ordering under it would collide with the aired rank on the deferred unique and claim
`source=tvdb` for a rank TMDB produced.

**An empty answer is unknown, never empty.** HTTP 200 with no episodes is how TheTVDB answers for an
ordering it does not hold, and a plugin that read that as authoritative deleted 194 seasons a scan. So
nothing is written, nothing is pruned, and the cursor records why - which is also how a walk that read
one page twice, and an ordering that pairs with nothing, are handled.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Final

from sqlalchemy import Row, delete, func, select
from sqlalchemy.dialects.postgresql import Insert, insert
from sqlalchemy.ext.asyncio import AsyncSession

from tv_watchlist.clients.errors import ProviderError
from tv_watchlist.clients.transport import scrubbed
from tv_watchlist.clients.tvdb_client import TvdbClient
from tv_watchlist.clock import utcnow
from tv_watchlist.constants import SPECIALS_ORDER_LABEL
from tv_watchlist.data.enums import EntityKind, ExternalSource, OrderType, SyncResourceType
from tv_watchlist.data.episode_order_lock import try_episode_order_locks
from tv_watchlist.data.models import Episode, EpisodeOrder, ExternalId, Title
from tv_watchlist.ingest.episode_order_busy_error import EpisodeOrderBusyError
from tv_watchlist.ingest.ingest_outcome import IngestOutcome
from tv_watchlist.ingest.sync_cursor import PostgresResponseCache
from tv_watchlist.ingest.tvdb_matching import MatchResult, StoredEpisode, match_tvdb_episodes
from tv_watchlist.models.tvdb.tvdb_episode import TvdbEpisode
from tv_watchlist.models.tvdb.tvdb_episodes_result import TvdbEpisodesResult
from tv_watchlist.services.tmdb_key import tmdb_key

_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)

_JOB: Final[str] = "episode_order"
_TMDB: Final[str] = ExternalSource.TMDB.value
_TVDB: Final[str] = ExternalSource.TVDB.value

#: The numbering this app derives from the episodes TMDB stored, carrying `source=tmdb`.
AIRED_ORDER_TYPE: Final[str] = OrderType.AIRED.value
#: Where season 0 goes. `SPECIALS_ORDER_LABEL` is what keeps it apart from a provider ordering.
SPECIALS_ORDER_TYPE: Final[str] = OrderType.ALTERNATE.value
NO_LABEL: Final[str] = ""
#: The specials bucket. A season like any other in the schema, and excluded from the aired walk alone.
SPECIALS_SEASON_NUMBER: Final[int] = 0
_KEY_SEPARATOR: Final[str] = "/"
#: Orderings this app produces itself, which no provider ordering may be written under.
RESERVED_ORDER_TYPES: Final[frozenset[str]] = frozenset({AIRED_ORDER_TYPE})
# Accepted as an episodes-endpoint path and answering exactly what the service's own aired ordering
# answered (measured 2026-09-15), so it is an alias rather than a type of its own (CLAUDE.md 2.1,
# item 6). Storing it would duplicate a whole ordering under a second name. It is spelled here because
# it is not a season type and never appears in the runtime list this module reads.
_ALIAS_ORDER_TYPES: Final[frozenset[str]] = frozenset({"default"})

# What the upsert compares and rewrites. The conflict key is absent: writing a row's identity back onto
# it is a no-op that only churns `updated_at`.
_ORDER_COLUMNS: Final[tuple[str, ...]] = ("sequence", "order_season_number", "order_episode_number", "source")
_CONFLICT: Final[tuple[str, ...]] = ("episode_id", "order_type", "label")
_UPDATED_AT: Final[str] = "updated_at"

#: `(episode_id, season_number, episode_number)` - the three facts a rank is computed from.
type EpisodeNumbering = tuple[uuid.UUID, int, int]
#: One stored row as this module reads it: the numbering plus the day it aired.
type EpisodeFacts = tuple[uuid.UUID, int, int, date | None]
#: What the ingest compares a stored row against, column for column.
type StoredRow = tuple[int, int | None, int | None, ExternalSource]


def _declared_length(column: str) -> int:
    """How wide the schema declared a column, read rather than restated so the two cannot drift."""
    declared = EpisodeOrder.__table__.columns[column].type.length
    if declared is None:  # pragma: no cover - order_type is String(n), so this cannot be reached
        raise ValueError(f"episode_order.{column} declares no length")
    return int(declared)


ORDER_TYPE_LENGTH: Final[int] = _declared_length("order_type")


@dataclass(frozen=True, slots=True)
class OrderSlot:
    """One episode's place in one numbering, before it is a row: the rank, and the pair the UI prints."""

    episode_id: uuid.UUID
    sequence: int
    order_season_number: int
    order_episode_number: int


# ---------------------------------------------------------------------------------------------------
# Pure projections. Everything above the class is a function of its arguments and needs no database.
# ---------------------------------------------------------------------------------------------------


def ranked(numbering: Iterable[EpisodeNumbering]) -> tuple[OrderSlot, ...]:
    """Dense 1-based ranks over `(season, episode)` ascending, whatever order the rows arrived in.

    Dense on purpose: the rank is a position in a list, not a copy of either number beside it. A gap in
    the provider's own numbering - a recap TMDB never listed - must not become a gap in the rank, or a
    span stored as a range would stop meaning the number of episodes the curator counted.
    """
    ordered = sorted(numbering, key=lambda entry: (entry[1], entry[2]))
    return tuple(
        OrderSlot(episode_id=episode_id, sequence=sequence, order_season_number=season, order_episode_number=episode)
        for sequence, (episode_id, season, episode) in enumerate(ordered, start=1)
    )


def aired_slots(numbering: Iterable[EpisodeNumbering]) -> tuple[OrderSlot, ...]:
    """The aired walk: `(season, episode)` ascending with the specials bucket excluded."""
    return ranked(entry for entry in numbering if entry[1] != SPECIALS_SEASON_NUMBER)


def specials_slots(numbering: Iterable[EpisodeNumbering]) -> tuple[OrderSlot, ...]:
    """The specials bucket as its own numbering, ranked from one. Kept, never dropped."""
    return ranked(entry for entry in numbering if entry[1] == SPECIALS_SEASON_NUMBER)


def provider_slots(tvdb_episodes: Sequence[TvdbEpisode], matched: Mapping[int, uuid.UUID]) -> tuple[OrderSlot, ...]:
    """One provider ordering as ranks over the episodes it was paired with, in its own numbering's order.

    Unpaired entries take no slot at all: a rank they held would point at nothing, and inventing a row
    for them is the one thing this whole module refuses to do.
    """
    paired = [episode for episode in tvdb_episodes if episode.id in matched]
    # Sorted by the ordering's own pair rather than trusted in arrival order, and stable, so a provider
    # that pages out of order still ranks the same way twice.
    ordered = sorted(paired, key=lambda episode: (episode.season_number, episode.number))
    return tuple(
        OrderSlot(
            episode_id=matched[episode.id],
            sequence=sequence,
            order_season_number=episode.season_number,
            order_episode_number=episode.number,
        )
        for sequence, episode in enumerate(ordered, start=1)
    )


def repeated_provider_ids(tvdb_episodes: Sequence[TvdbEpisode]) -> tuple[int, ...]:
    """The provider ids a walk returned more than once, which is the shape a truncated walk takes.

    `all_series_episodes` follows `links.next` to the last page, so a walk is complete unless it stopped
    on its own loop guard - and a loop repeats a page, which repeats its ids. The schema could not store
    a repeat anyway: `uq(episode_id, order_type, label)` allows one row per episode per ordering.
    """
    seen: set[int] = set()
    # A dict rather than a list, so noticing a third copy of an id costs the same as noticing the second.
    repeated: dict[int, None] = {}
    for episode in tvdb_episodes:
        if episode.id in seen:
            repeated[episode.id] = None
        seen.add(episode.id)
    return tuple(repeated)


def refusal_for(season_type: str) -> str | None:
    """Why this name may not become an `order_type`, or `None` when it may. The one place that decides."""
    if not season_type:
        return "is a blank ordering name"
    if len(season_type) > ORDER_TYPE_LENGTH:
        return f"is {len(season_type)} characters, past the {ORDER_TYPE_LENGTH} the order_type column holds"
    if season_type in _ALIAS_ORDER_TYPES:
        return "is an alias for an ordering the service already lists under its own name, not a type of its own"
    if season_type in RESERVED_ORDER_TYPES:
        return "names an ordering this app produces itself"
    return None


def provider_order_type(season_type: str) -> str | None:
    """The `order_type` one runtime season type is written under, or `None` when it may not be written.

    Identity, deliberately. The name comes from `GET /v4/seasons/types` and is stored exactly as the
    service spells it, so a type this app has never seen needs no migration and no code change. The four
    refusals are `refusal_for`'s, and each of them would otherwise cost something concrete: a blank or
    oversized name aborts the transaction on insert, an alias stores one ordering twice, and a name this
    app already produces collides with it on the deferred unique while claiming the wrong `source`.

    The predicate form, for a caller that wants the name; the ingest wants the reason and calls
    `refusal_for` instead.
    """
    return None if refusal_for(season_type) is not None else season_type


def episodes_key(series_id: int, season_type: str) -> str:
    """The `sync_state.resource_key` this ingest records one ordering's walk against.

    The client keys each *page* it fetched; this keys the walk as a whole, because only the ingest can
    tell an answer that arrived from an answer that meant anything. Nothing is recorded here on success:
    an expired `next_attempt_at` reads as due, which is what a recovered ordering should be.
    """
    return f"{series_id}{_KEY_SEPARATOR}{season_type}"


def order_values(
    title_id: uuid.UUID, order_type: str, label: str, source: ExternalSource, slot: OrderSlot
) -> dict[str, object]:
    """One slot as an `episode_order` row."""
    return {
        "title_id": title_id,
        "episode_id": slot.episode_id,
        "order_type": order_type,
        "label": label,
        "sequence": slot.sequence,
        "order_season_number": slot.order_season_number,
        "order_episode_number": slot.order_episode_number,
        "source": source,
    }


def comparable_row(source: ExternalSource, slot: OrderSlot) -> StoredRow:
    """The four columns a stored row is compared on, in the order `_ORDER_COLUMNS` names them.

    A slot that compares equal to what is stored produces no statement at all, which is what keeps a
    nightly pass from rewriting every row and churning `updated_at` for nothing.
    """
    return (slot.sequence, slot.order_season_number, slot.order_episode_number, source)


def _upsert() -> Insert:
    """One row per episode per ordering, re-ranked in place.

    `ON CONFLICT (episode_id, order_type, label)` rather than a plain UPDATE, because one statement has
    to cover both the episodes that moved and the ones that are new. The rank column is the one the
    deferred unique guards, which is what lets every sequence shift by one inside a single statement.
    """
    statement = insert(EpisodeOrder)
    return statement.on_conflict_do_update(
        index_elements=list(_CONFLICT),
        set_={name: statement.excluded[name] for name in _ORDER_COLUMNS} | {_UPDATED_AT: func.now()},
    )


def resource_label(title: Title) -> str:
    """What a log line calls this work: its TMDB pointer when it has one, else its own row id.

    A hand-entered title with no provider match is a first-class record here as everywhere else, so it
    is named by the one identifier it always has rather than left out of the log.
    """
    if title.tmdb_id is None or title.tmdb_id <= 0:
        return str(title.id)
    return tmdb_key(title.media_type, title.tmdb_id)


async def tvdb_series_id_for(session: AsyncSession, title: Title) -> int | None:
    """The TheTVDB series id TMDB supplied, or nothing. NEVER a search.

    TheTVDB's own search ranked the One Piece anime eighth, behind a 2023 live-action namesake, so the
    id comes from `external_ids` and this module has no search method to reach for.
    """
    value = await session.scalar(
        select(ExternalId.value).where(
            ExternalId.title_id == title.id,
            ExternalId.source == ExternalSource.TVDB,
            ExternalId.entity_kind == EntityKind.TITLE,
        )
    )
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        # A stored id that is not a number cannot address the service; that is a fact to report, not an
        # exception to raise into a nightly job.
        return None


class EpisodeOrderIngest:
    """Every numbering of one title, over one session's transaction.

    The session is the caller's and nothing here commits: a pass that wrote half an ordering and then
    recorded a cursor saying the ordering was current would leave the projection permanently wrong.
    """

    def __init__(self, session: AsyncSession, tvdb: TvdbClient, *, clock: Callable[[], datetime] = utcnow) -> None:
        self._session = session
        self._tvdb = tvdb
        # The same cursor table the client writes through, so a backoff this ingest records is honoured
        # rather than merely stored (CLAUDE.md section 9.2).
        self._cursors = PostgresResponseCache(session, clock=clock)

    @staticmethod
    def upsert_shape() -> Insert:
        """The one upsert this module issues, so its SQL is proved without a database (CLAUDE.md 16.4)."""
        return _upsert()

    async def rank_aired(self, title: Title) -> IngestOutcome:
        """The two numberings TMDB's own episodes produce: the aired rank, and the specials beside it."""
        started = time.monotonic()
        resource = resource_label(title)
        self._log_start(_TMDB, resource)
        numbering = [(facts[0], facts[1], facts[2]) for facts in await self._episode_facts(title.id)]
        outcome = await self._stored_ordering(
            title.id, AIRED_ORDER_TYPE, NO_LABEL, ExternalSource.TMDB, aired_slots(numbering)
        )
        outcome += await self._stored_ordering(
            title.id, SPECIALS_ORDER_TYPE, SPECIALS_ORDER_LABEL, ExternalSource.TMDB, specials_slots(numbering)
        )
        return self._log_end(_TMDB, resource, outcome, started)

    async def ingest_tvdb_orders(self, title: Title) -> dict[str, IngestOutcome]:
        """Every ordering the service offers today, keyed by the name it offered it under.

        The list is read at runtime, so the keys of the result are whatever TheTVDB currently has - an
        eighth type appears here the day it appears there, and needs nothing from this code.
        """
        started = time.monotonic()
        resource = resource_label(title)
        self._log_start(_TVDB, resource)
        outcomes: dict[str, IngestOutcome] = {}
        series_id = await tvdb_series_id_for(self._session, title)
        if series_id is None:
            self._log_skip(resource, "this title carries no TheTVDB id, and none is ever searched for")
        else:
            season_types = await self._season_types(resource)
            # Read once for the whole pass rather than once per ordering: the projection cannot change
            # underneath a transaction, and seven orderings would otherwise scan the same episodes seven
            # times to learn the same thing.
            stored = await self._stored_episodes(title.id) if season_types else ()
            for season_type in season_types:
                outcomes[season_type] = await self._one_order(title.id, series_id, season_type, stored)
        self._log_end(_TVDB, resource, summed(outcomes), started)
        return outcomes

    # -- the provider leg ---------------------------------------------------------------------------

    async def _season_types(self, resource: str) -> tuple[str, ...]:
        """The orderings the service offers right now, or nothing at all when it cannot be asked."""
        if not self._tvdb.configured:
            self._log_skip(resource, "TheTVDB is not configured, so its orderings are a disabled feature")
            return ()
        try:
            return tuple(entry.type for entry in await self._tvdb.season_types())
        except ProviderError as error:
            # The client has already recorded the failure against its own cursor and logged the call.
            self._log_skip(resource, f"{type(error).__name__}: {error}")
            return ()

    async def _one_order(
        self, title_id: uuid.UUID, series_id: int, season_type: str, stored: Sequence[StoredEpisode]
    ) -> IngestOutcome:
        """One ordering, from the runtime list to the rows - or to a recorded reason for writing none."""
        key = episodes_key(series_id, season_type)
        refusal = refusal_for(season_type)
        if refusal is not None:
            return await self._refused(key, season_type, refusal)
        # Past the refusals, the name is stored exactly as the service spelled it - which is the whole
        # of `provider_order_type`, stated here as the assignment it is.
        order_type = season_type
        if not await self._cursors.is_due(_TVDB, SyncResourceType.TVDB_EPISODES.value, key):
            self._log_order(key, order_type, "throttled", pages=0, episodes=0, match=MatchResult())
            return IngestOutcome(skipped=1, outcome="throttled")
        try:
            result = await self._tvdb.all_series_episodes(series_id, season_type)
        except ProviderError as error:
            return await self._refused(key, season_type, f"{type(error).__name__}: {error}")
        return await self._from_walk(title_id, key, order_type, result, stored)

    async def _from_walk(
        self,
        title_id: uuid.UUID,
        key: str,
        order_type: str,
        result: TvdbEpisodesResult,
        stored: Sequence[StoredEpisode],
    ) -> IngestOutcome:
        """What one completed walk becomes. Three of the four answers write nothing."""
        if not result.known:
            return await self._refused(key, order_type, "answered with no episodes, which is unknown, not empty")
        repeated = repeated_provider_ids(result.episodes)
        if repeated:
            return await self._refused(
                key, order_type, f"repeated {len(repeated)} episode ids, so the walk read a page it had already read"
            )
        collected = len(result.episodes)
        if result.reported is not None and collected != result.reported:
            # The service said how many the ordering holds; the walk brought back a different number. A
            # short read that reported success is worse than one that failed, and writing it would prune
            # every episode on the pages that never arrived (CLAUDE.md section 9.2).
            return await self._refused(
                key, order_type, f"read {collected} of the {result.reported} episodes it says this ordering holds"
            )
        match = match_tvdb_episodes(result.episodes, stored)
        slots = provider_slots(result.episodes, match.matched)
        self._log_order(key, order_type, "fresh", pages=result.pages, episodes=collected, match=match)
        if not slots:
            # A real answer that pairs with nothing this projection holds. Writing nothing is right, and
            # pruning would be the empty-answer mistake one level up: it would delete an ordering that
            # is still correct because this pass could not recognise it.
            return IngestOutcome(outcome="not-modified")
        return await self._stored_ordering(title_id, order_type, NO_LABEL, ExternalSource.TVDB, slots)

    async def _refused(self, key: str, subject: str, reason: str) -> IngestOutcome:
        """Write nothing, record why against the walk's own cursor, and earn the backoff that follows."""
        message = f"{subject}: {reason}"
        await self._cursors.record_failure(_TVDB, SyncResourceType.TVDB_EPISODES.value, key, message)
        _LOGGER.warning(
            "ingest_refused job=%s source=%s resource=%s reason=%s", _JOB, _TVDB, scrubbed(key), scrubbed(message)
        )
        return IngestOutcome(skipped=1, outcome="failed")

    # -- the writing leg ----------------------------------------------------------------------------

    async def _episode_facts(self, title_id: uuid.UUID) -> tuple[EpisodeFacts, ...]:
        """Every episode of one title, in the four facts every numbering here is built from."""
        rows = await self._session.execute(
            select(Episode.id, Episode.season_number, Episode.episode_number, Episode.air_date).where(
                Episode.title_id == title_id
            )
        )
        return tuple((row.id, row.season_number, row.episode_number, row.air_date) for row in rows)

    async def _stored_episodes(self, title_id: uuid.UUID) -> tuple[StoredEpisode, ...]:
        """The same episodes as the matcher needs them: an id, a day, and where the aired walk put it.

        The rank is derived here rather than read back from `episode_order`, so pairing a provider
        ordering never depends on `rank_aired` having run first.
        """
        facts = await self._episode_facts(title_id)
        ranks = {slot.episode_id: slot.sequence for slot in aired_slots((row[0], row[1], row[2]) for row in facts)}
        return tuple(StoredEpisode(episode_id=row[0], air_date=row[3], aired_rank=ranks.get(row[0])) for row in facts)

    async def _stored_ordering(
        self,
        title_id: uuid.UUID,
        order_type: str,
        label: str,
        source: ExternalSource,
        slots: Sequence[OrderSlot],
    ) -> IngestOutcome:
        """One numbering written whole: what left it is pruned, what moved is re-ranked, the rest is left.

        A pass over an unchanged numbering issues no data mutation, which is what keeps a nightly
        refresh from rewriting every row and churning `updated_at` for nothing.
        """
        if not await try_episode_order_locks(self._session, (title_id,), shared=False):
            raise EpisodeOrderBusyError("Episode numbering is busy; retry the ingest.")
        existing = await self._existing(title_id, order_type, label)
        wanted = {slot.episode_id: slot for slot in slots}
        pruned = await self._pruned(title_id, order_type, label, [key for key in existing if key not in wanted])
        rows: list[dict[str, object]] = []
        outcome = IngestOutcome(outcome="not-modified")
        for episode_id, slot in wanted.items():
            stored = existing.get(episode_id)
            if stored is not None and stored == comparable_row(source, slot):
                outcome += IngestOutcome(unchanged=1, outcome="not-modified")
                continue
            rows.append({"id": uuid.uuid4(), **order_values(title_id, order_type, label, source, slot)})
            outcome += IngestOutcome(inserted=int(stored is None), updated=int(stored is not None), outcome="fresh")
        if rows:
            # One statement for the whole numbering, inserts and re-ranks together. Every sequence may
            # shift by one inside it because the unique on (title_id, order_type, label, sequence) is
            # DEFERRABLE INITIALLY DEFERRED and is therefore checked once, at commit.
            await self._session.execute(_upsert(), rows)
        self._log_rows(order_type, label, outcome, pruned)
        return outcome

    async def _existing(self, title_id: uuid.UUID, order_type: str, label: str) -> dict[uuid.UUID, StoredRow]:
        rows = await self._session.execute(
            select(
                EpisodeOrder.episode_id,
                EpisodeOrder.sequence,
                EpisodeOrder.order_season_number,
                EpisodeOrder.order_episode_number,
                EpisodeOrder.source,
            ).where(
                EpisodeOrder.title_id == title_id,
                EpisodeOrder.order_type == order_type,
                EpisodeOrder.label == label,
            )
        )
        return {row.episode_id: _stored_row(row) for row in rows}

    async def _pruned(self, title_id: uuid.UUID, order_type: str, label: str, stale: Sequence[uuid.UUID]) -> int:
        """Rows for episodes this numbering no longer contains. No statement when there are none.

        Safe here and only here: the caller has already refused every answer it could not trust, so a
        row is deleted because the ordering really stopped containing that episode.
        """
        if not stale:
            return 0
        result = await self._session.execute(
            delete(EpisodeOrder).where(
                EpisodeOrder.title_id == title_id,
                EpisodeOrder.order_type == order_type,
                EpisodeOrder.label == label,
                EpisodeOrder.episode_id.in_(stale),
            )
        )
        return result.rowcount

    # -- logging ------------------------------------------------------------------------------------

    def _log_start(self, source: str, resource: str) -> None:
        _LOGGER.info("ingest_start job=%s source=%s resource=%s", _JOB, source, scrubbed(resource))

    def _log_end(self, source: str, resource: str, outcome: IngestOutcome, started: float) -> IngestOutcome:
        """The end record every pass writes, zeros included: a run that changed nothing must say so."""
        _LOGGER.info(
            "ingest_end job=%s source=%s resource=%s inserted=%d updated=%d unchanged=%d skipped=%d"
            " elapsed_ms=%d outcome=%s",
            _JOB,
            source,
            scrubbed(resource),
            outcome.inserted,
            outcome.updated,
            outcome.unchanged,
            outcome.skipped,
            int((time.monotonic() - started) * 1000),
            outcome.outcome,
        )
        return outcome

    def _log_rows(self, order_type: str, label: str, outcome: IngestOutcome, pruned: int) -> None:
        _LOGGER.info(
            "ingest_rows job=%s order_type=%s label=%s inserted=%d updated=%d unchanged=%d pruned=%d",
            _JOB,
            scrubbed(order_type),
            scrubbed(label),
            outcome.inserted,
            outcome.updated,
            outcome.unchanged,
            pruned,
        )

    def _log_order(
        self, key: str, order_type: str, outcome: str, *, pages: int, episodes: int, match: MatchResult
    ) -> None:
        """One record per ordering. `matched` against `episodes` is how a thin pairing is noticed."""
        _LOGGER.info(
            "ingest_order job=%s source=%s resource=%s order_type=%s pages=%d episodes=%d matched=%d"
            " by_date=%d by_absolute=%d unmatched=%d outcome=%s",
            _JOB,
            _TVDB,
            scrubbed(key),
            scrubbed(order_type),
            pages,
            episodes,
            len(match.matched),
            match.by_air_date,
            match.by_absolute_number,
            len(match.unmatched),
            outcome,
        )

    def _log_skip(self, resource: str, reason: str) -> None:
        _LOGGER.info(
            "ingest_skipped job=%s source=%s resource=%s reason=%s", _JOB, _TVDB, scrubbed(resource), scrubbed(reason)
        )


def _stored_row(row: Row[tuple[object, ...]]) -> StoredRow:
    """One stored row as the tuple `_comparable` produces, so the two can be compared directly."""
    return (row.sequence, row.order_season_number, row.order_episode_number, row.source)


def summed(outcomes: Mapping[str, IngestOutcome]) -> IngestOutcome:
    """Every ordering's result folded into one, for the pass's own end record and for a caller's."""
    total = IngestOutcome()
    for outcome in outcomes.values():
        total += outcome
    return total
