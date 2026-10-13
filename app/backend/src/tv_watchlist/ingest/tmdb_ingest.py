"""TMDB into `title` / `season` / `episode` / `external_id` / `artwork`.

Three rules shape every line here.

**Minutes become seconds once.** TMDB sends `runtime` in whole minutes; `minutes_to_seconds` is the one
place it is multiplied, and no minutes column exists anywhere downstream (CLAUDE.md section 11.2, rule 7).

**An unchanged row produces no statement.** Every write is preceded by a read and a field-by-field
comparison, so a second pass over identical bytes leaves `updated_at` alone and the phase gate's "zero
episode-row updates" is a property of the code rather than a hope.

**Numbering is stored verbatim.** One Piece's season 2 runs 62-77 and is written 62-77. TMDB numbers
anime absolute-continuously inside season buckets, so `(season_number, episode_number)` is a key and
never a human `SxxEyy`; turning a numbering into a rank is `episode_order`'s job, not this module's.

One consequence a reader should know before changing anything here: `ingest_tv` awaits provider round
trips *inside* the caller's transaction, so a series holds it open for as many HTTP calls as it has
seasons. That is deliberate. The cursor writes and the row writes have to commit or roll back together -
a cursor recorded outside this transaction would claim a series was current after the rows describing it
had been rolled back, and the next pass would skip the refetch that would have healed it. This is a
single-user local app with one ingest at a time, so a long-held transaction blocks nothing; if that ever
stops being true, the fix is a per-season transaction, never a second connection for the cursors.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Final

from sqlalchemy import Row, Select, func, select, update
from sqlalchemy.dialects.postgresql import Insert, insert
from sqlalchemy.ext.asyncio import AsyncSession

from tv_watchlist.clients.errors import ProviderError, ProviderNotFoundError
from tv_watchlist.clients.tmdb_client import TmdbClient
from tv_watchlist.clock import utcnow
from tv_watchlist.constants import TMDB_CACHE_CEILING_DAYS, TMDB_IMAGE_BASE_URL, TMDB_POSTER_SIZE
from tv_watchlist.data.base import Base
from tv_watchlist.data.enums import ArtworkKind, EntityKind, ExternalSource, MediaType, SyncResourceType
from tv_watchlist.data.episode_order_lock import try_episode_order_locks
from tv_watchlist.data.models import Artwork, Episode, ExternalId, Season, SyncState, Title
from tv_watchlist.ingest.artwork_candidate import ArtworkCandidate
from tv_watchlist.ingest.episode_order_busy_error import EpisodeOrderBusyError
from tv_watchlist.ingest.ingest_outcome import IngestOutcome
from tv_watchlist.ingest.sync_cursor import PostgresResponseCache, ceiling_cutoff
from tv_watchlist.models.tmdb.tmdb_episode import TmdbEpisode
from tv_watchlist.models.tmdb.tmdb_external_ids import TmdbExternalIds
from tv_watchlist.models.tmdb.tmdb_movie import TmdbMovie
from tv_watchlist.models.tmdb.tmdb_search_hit import TmdbMediaType
from tv_watchlist.models.tmdb.tmdb_season import TmdbSeason
from tv_watchlist.models.tmdb.tmdb_season_summary import TmdbSeasonSummary
from tv_watchlist.models.tmdb.tmdb_tv import TmdbTv
from tv_watchlist.resolver.match_key import match_key, release_year
from tv_watchlist.services.artwork_cache import ArtworkCache

_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)

# The one place a duration is scaled. Declared rather than written inline so the grep for "* 60" lands
# on a named constant with this comment attached to it.
SECONDS_PER_MINUTE: Final[int] = 60

_SOURCE: Final[str] = ExternalSource.TMDB.value
_ISO_DATE_LENGTH: Final[int] = 10
# `GET /3/configuration` is a singleton, so its cursor is keyed by a name rather than an id. This
# mirrors `tmdb_client._CONFIGURATION_KEY`, the same way the other resource keys here do.
_CONFIGURATION_RESOURCE_KEY: Final[str] = "configuration"
# `clients/` keeps its own `Literal["movie", "tv"]` because it may not import `data/`. This is the one
# boundary that knows both vocabularies, so this is the one place they are mapped onto each other.
_PROVIDER_MEDIA_TYPE: Final[dict[MediaType, TmdbMediaType]] = {MediaType.MOVIE: "movie", MediaType.TV: "tv"}
_TITLE_RESOURCE: Final[dict[MediaType, SyncResourceType]] = {
    MediaType.MOVIE: SyncResourceType.TMDB_MOVIE,
    MediaType.TV: SyncResourceType.TMDB_TV,
}

# What each upsert compares and rewrites. The conflict key itself is absent from every `set_`: writing
# a row's own identity back onto it is a no-op that only churns `updated_at`.
_TITLE_COLUMNS: Final[tuple[str, ...]] = (
    "name",
    "original_name",
    "match_key",
    "overview",
    "first_air_date",
    "last_air_date",
    "runtime_seconds",
    "episode_count",
    "season_count",
    "status",
    "original_language",
)
_SEASON_COLUMNS: Final[tuple[str, ...]] = ("name", "overview", "air_date", "episode_count")
_EPISODE_COLUMNS: Final[tuple[str, ...]] = (
    "title_id",
    "season_id",
    "season_number",
    "episode_number",
    "name",
    "overview",
    "air_date",
    "runtime_seconds",
    "production_code",
)
# `local_path` is deliberately absent: the ingest never supplies one, and listing it here would erase a
# cached file's path on every refresh, which is exactly the byte cache this design is trying to keep.
_ARTWORK_COLUMNS: Final[tuple[str, ...]] = (
    "entity_kind",
    "kind",
    "width",
    "height",
    "aspect_ratio",
    "language",
    "vote_average",
    "title_id",
)

_UPDATED_AT: Final[str] = "updated_at"
_ENGLISH: Final[str] = "en"


# ---------------------------------------------------------------------------------------------------
# Pure projections. Everything below the class is a function of its arguments and needs no database.
# ---------------------------------------------------------------------------------------------------


def minutes_to_seconds(runtime_minutes: int | None) -> int | None:
    """Whole TMDB minutes as whole seconds. `0` and anything negative become `None`.

    Every duration column carries `CHECK <column> > 0`, so a zero runtime is an absent one: TMDB sends
    `0` for an episode nobody has timed, and storing it would be a claim the data does not support.
    """
    if runtime_minutes is None or runtime_minutes <= 0:
        return None
    return runtime_minutes * SECONDS_PER_MINUTE


def tmdb_date(raw: str | None) -> date | None:
    """A TMDB date string as a `date`. `""`, `None` and anything unparseable are all simply absent.

    TMDB sends `""` for an undated work. Coercing at the model would turn one missing date into a
    validation failure for a whole page, so the strings arrive here intact and are read at this boundary.
    """
    if not raw or len(raw) != _ISO_DATE_LENGTH:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _length_of(model: type[Base], column: str) -> int:
    """How wide the schema actually declared that column. Read, never restated, so the two cannot drift."""
    declared = model.__table__.columns[column].type.length
    if declared is None:  # pragma: no cover - only an unbounded Text column, which nothing here clips
        raise ValueError(f"{model.__tablename__}.{column} declares no length")
    return int(declared)


def _clipped(value: str, model: type[Base], column: str) -> str:
    """The value as the column can actually hold it, and one log record whenever that costs something.

    Clipped rather than passed through: a value one character over the declared width raises
    `StringDataRightTruncation`, which aborts the whole transaction and loses a title over a stray
    subtitle. The limit comes from the column itself, so widening the schema widens this too.

    A silent clip is the dangerous kind. `title.match_key` is `String(255)` and is what the workbook side
    matches on (Ruling 32), so a truncation there can turn into a title that never resolves and no
    evidence of why - hence the record, emitted only when characters were actually dropped.
    """
    limit = _length_of(model, column)
    if len(value) <= limit:
        return value
    _LOGGER.info("clipped table=%s column=%s from=%d to=%d", model.__tablename__, column, len(value), limit)
    return value[:limit]


def _fitted(value: str, model: type[Base], column: str) -> str | None:
    """The same clip for a nullable column, where TMDB's empty string is stored as `NULL`."""
    return _clipped(value, model, column) or None


def _required(value: str, model: type[Base], column: str) -> str:
    """The clip for a NOT NULL column, where an empty string is still a value and `NULL` is not."""
    return _clipped(value, model, column)


def _or_none(value: str) -> str | None:
    """TMDB's empty string for a nullable column. Stored as `NULL`, so a comparison has one absent form."""
    return value or None


def title_values_for_movie(details: TmdbMovie) -> dict[str, object]:
    """One film as a `title` row. `runtime` is minutes here and seconds from here on."""
    return {
        "media_type": MediaType.MOVIE,
        "tmdb_id": details.id,
        "name": _required(details.title, Title, "name"),
        "original_name": _fitted(details.original_title, Title, "original_name"),
        "match_key": _required(
            match_key(details.title, year=release_year(details.release_date or "")), Title, "match_key"
        ),
        "overview": _or_none(details.overview),
        "first_air_date": tmdb_date(details.release_date),
        "last_air_date": None,
        "runtime_seconds": minutes_to_seconds(details.runtime),
        "episode_count": None,
        "season_count": None,
        "status": _fitted(details.status, Title, "status"),
        "original_language": _fitted(details.original_language, Title, "original_language"),
    }


def title_values_for_tv(details: TmdbTv) -> dict[str, object]:
    """One series as a `title` row.

    `runtime_seconds` stays `None`. `episode_run_time` is a *per-episode* figure, and section 11.2 rule 8
    sums `title.runtime_seconds` for movie entries: a typical episode length stored there would silently
    corrupt every category runtime total.
    """
    return {
        "media_type": MediaType.TV,
        "tmdb_id": details.id,
        "name": _required(details.name, Title, "name"),
        "original_name": _fitted(details.original_name, Title, "original_name"),
        "match_key": _required(
            match_key(details.name, year=release_year(details.first_air_date or "")), Title, "match_key"
        ),
        "overview": _or_none(details.overview),
        "first_air_date": tmdb_date(details.first_air_date),
        "last_air_date": tmdb_date(details.last_air_date),
        "runtime_seconds": None,
        "episode_count": details.number_of_episodes,
        "season_count": details.number_of_seasons,
        "status": _fitted(details.status, Title, "status"),
        "original_language": _fitted(details.original_language, Title, "original_language"),
    }


def season_values(
    title_id: uuid.UUID, summary: TmdbSeasonSummary, details: TmdbSeason | None = None
) -> dict[str, object]:
    """One season as a row. The summary always answers; the details document overrides it when it arrived.

    Season 0 is the specials bucket, and it is a season like any other: it is kept, and it is why
    `seasons` outnumbers `number_of_seasons`.
    """
    episodes = summary.episode_count if details is None else len(details.episodes)
    source = summary if details is None else details
    return {
        "title_id": title_id,
        "season_number": summary.season_number,
        "name": _fitted(source.name, Season, "name"),
        "overview": _or_none(source.overview),
        "air_date": tmdb_date(source.air_date),
        "episode_count": episodes,
    }


def episode_values(title_id: uuid.UUID, season_id: uuid.UUID, episode: TmdbEpisode) -> dict[str, object]:
    """One episode as a row, numbered exactly as TMDB numbers it.

    `title_id` is denormalised on purpose so every order query stays a single join, and it is written
    from the same title in the same transaction as `season.title_id` - the cross-table invariant a CHECK
    cannot express, and which the ingest test suite asserts.
    """
    return {
        "title_id": title_id,
        "season_id": season_id,
        "season_number": episode.season_number,
        "episode_number": episode.episode_number,
        "tmdb_episode_id": episode.id,
        "name": _fitted(episode.name, Episode, "name"),
        "overview": _or_none(episode.overview),
        "air_date": tmdb_date(episode.air_date),
        "runtime_seconds": minutes_to_seconds(episode.runtime),
        "production_code": _fitted(episode.production_code, Episode, "production_code"),
    }


def artwork_values(title_id: uuid.UUID, candidate: ArtworkCandidate) -> dict[str, object]:
    """One image as a metadata row. Bytes are never stored here - `local_path` is the cache's to set."""
    return {
        "entity_kind": EntityKind.TITLE,
        "kind": candidate.kind,
        "source": ExternalSource.TMDB,
        "remote_path": _required(candidate.remote_path, Artwork, "remote_path"),
        "width": candidate.width,
        "height": candidate.height,
        "aspect_ratio": candidate.aspect_ratio,
        "language": None if candidate.language is None else _fitted(candidate.language, Artwork, "language"),
        "vote_average": candidate.vote_average,
        "is_primary": False,
        "title_id": title_id,
    }


def episode_rows(
    title_id: uuid.UUID,
    season_id: uuid.UUID,
    episodes: Sequence[TmdbEpisode],
    known: dict[int, dict[str, object]],
) -> tuple[list[dict[str, object]], IngestOutcome]:
    """The rows one season needs written, with `known` folded forward as each is decided.

    Folding matters because `tmdb_episode_id` is unique across the whole table, not per season, and TMDB
    genuinely re-parents episodes - One Piece was re-cut into 23 seasons in 2023. Without the fold, an id
    that appears under two seasons of one payload would be counted twice as an insert, and both rows
    would reach one `ON CONFLICT DO UPDATE` statement, which Postgres refuses outright ("cannot affect
    row a second time"). With it, the second sighting is an update of the first, and an id repeated
    inside a single season is dropped rather than queued twice.
    """
    rows: list[dict[str, object]] = []
    outcome = IngestOutcome(outcome="not-modified")
    queued: set[int] = set()
    for episode in episodes:
        if episode.id in queued:
            # The same id twice in one statement is a refusal, not an update. TMDB listing it twice in
            # one season is a catalogue error, so it is skipped and the first sighting stands.
            outcome += IngestOutcome(skipped=1, outcome="not-modified")
            continue
        values = episode_values(title_id, season_id, episode)
        existing = known.get(episode.id)
        if existing is not None and not changed_columns(existing, values):
            outcome += IngestOutcome(unchanged=1, outcome="not-modified")
            continue
        rows.append({"id": uuid.uuid4(), **values})
        queued.add(episode.id)
        outcome += IngestOutcome(inserted=int(existing is None), updated=int(existing is not None), outcome="fresh")
        known[episode.id] = dict(values)
    return rows, outcome


def changed_columns(existing: Mapping[str, object], values: Mapping[str, object]) -> dict[str, object]:
    """Only the columns whose value actually moved. An empty result means no statement is issued at all."""
    return {name: value for name, value in values.items() if existing.get(name) != value}


def primary_candidate(candidates: Sequence[ArtworkCandidate], original_language: str | None) -> ArtworkCandidate | None:
    """The highest-voted image in the work's own language, else in English, else the highest-voted at all."""
    for language in (original_language, _ENGLISH):
        if language is None:
            continue
        preferred = [candidate for candidate in candidates if candidate.language == language]
        if preferred:
            return _best_voted(preferred)
    return _best_voted(candidates) if candidates else None


def _best_voted(candidates: Sequence[ArtworkCandidate]) -> ArtworkCandidate:
    """An unvoted image loses to any voted one, and ties keep the order the provider listed them in."""
    return max(candidates, key=lambda candidate: candidate.vote_average or Decimal(-1))


def movie_key(tmdb_id: int) -> str:
    """The `sync_state.resource_key` `TmdbClient.movie_details` writes for this film."""
    return str(tmdb_id)


def tv_key(tmdb_id: int) -> str:
    """The `sync_state.resource_key` `TmdbClient.tv_details` writes for this series."""
    return str(tmdb_id)


def season_key(tmdb_id: int, season_number: int) -> str:
    """The `sync_state.resource_key` `TmdbClient.season_details` writes for one season.

    The client owns these shapes; they are rebuilt here because the gate has to read the cursor the
    client wrote. A drift would make the backoff unreadable rather than wrong, so the ingest suite
    asserts this equals what a real fetch stores.
    """
    return f"{tmdb_id}/{season_number}"


def external_ids_key(media_type: MediaType, tmdb_id: int) -> str:
    """The `sync_state.resource_key` `TmdbClient.external_ids` writes."""
    return f"{_PROVIDER_MEDIA_TYPE[media_type]}/{tmdb_id}"


def artwork_candidates(
    poster_path: str | None, backdrop_path: str | None
) -> tuple[list[ArtworkCandidate], list[ArtworkCandidate]]:
    """The posters and backdrops a details document offers, which today is at most one of each.

    A details payload carries a path and nothing else - no width, no language, no vote. When an images
    endpoint is added, it fills the rest of `ArtworkCandidate` and this function grows a second source.
    """
    posters = [ArtworkCandidate(kind=ArtworkKind.POSTER, remote_path=poster_path)] if poster_path else []
    backdrops = [ArtworkCandidate(kind=ArtworkKind.BACKDROP, remote_path=backdrop_path)] if backdrop_path else []
    return posters, backdrops


# ---------------------------------------------------------------------------------------------------
# The statements. Parameterless, so each is one compiled shape executed with bound rows.
# ---------------------------------------------------------------------------------------------------


def _upsert(model: type[Base], conflict: Sequence[str], columns: Sequence[str]) -> Insert:
    """An upsert on one unique key that rewrites only `columns`, plus the stamp that says it did."""
    statement = insert(model)
    return statement.on_conflict_do_update(
        index_elements=list(conflict),
        set_={name: statement.excluded[name] for name in columns} | {_UPDATED_AT: func.now()},
    )


def _title_upsert() -> Insert:
    return _upsert(Title, ("media_type", "tmdb_id"), _TITLE_COLUMNS)


def _season_upsert() -> Insert:
    return _upsert(Season, ("title_id", "season_number"), _SEASON_COLUMNS)


def _episode_upsert() -> Insert:
    # The conflict key is `tmdb_episode_id`, not `(season_id, episode_number)`: TMDB re-seasons anime -
    # One Piece was re-cut into 23 seasons in 2023 - and an episode that moved must follow its own id
    # rather than be inserted a second time under its new season.
    return _upsert(Episode, ("tmdb_episode_id",), _EPISODE_COLUMNS)


def _external_id_upsert() -> Insert:
    # Nothing to update: `(source, entity_kind, value)` IS the row. A second ingest re-offers the same
    # three, and the right answer is silence.
    return insert(ExternalId).on_conflict_do_nothing(index_elements=["source", "entity_kind", "value"])


def _artwork_upsert() -> Insert:
    return _upsert(Artwork, ("source", "remote_path"), _ARTWORK_COLUMNS)


def _mapping_of(row: Row[tuple[object, ...]]) -> dict[str, object]:
    return dict(row._mapping)  # noqa: SLF001 - Row._mapping is SQLAlchemy 2.0's public read accessor


def _selected(model: type[Base], columns: Sequence[str]) -> Select[tuple[object, ...]]:
    return select(*(getattr(model, name) for name in columns))


class TmdbIngest:
    """One pass of TMDB into the projection, over one session's transaction.

    The session is the caller's, and nothing here commits: an ingest that wrote half a series and then
    recorded a cursor saying the series was current would leave the projection permanently short.
    """

    def __init__(
        self,
        session: AsyncSession,
        client: TmdbClient,
        *,
        artwork: ArtworkCache | None = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._session = session
        self._client = client
        self._artwork = artwork
        self._clock = clock
        # The same cursor table the client writes through, read here so the backoff it records is
        # actually honoured rather than merely stored (CLAUDE.md section 9.2).
        self._cursors = PostgresResponseCache(session, clock=clock)
        self._image_base: str | None = None

    @staticmethod
    def upsert_shapes() -> tuple[Insert, ...]:
        """Every upsert this module issues, so their SQL is proved without a database (CLAUDE.md 16.4)."""
        return (
            _title_upsert(),
            _season_upsert(),
            _episode_upsert(),
            _external_id_upsert(),
            _artwork_upsert(),
        )

    async def ensure_title(self, media_type: MediaType, tmdb_id: int) -> Title | None:
        """The stored work for this TMDB id, fetched and upserted first, with its external ids beside it.

        `None` when the provider had nothing new to say and no row exists locally yet - a 304 against an
        empty projection is not a title, and inventing one would be a row nothing could fill in.
        """
        title, _, _ = await self._ensured(media_type, tmdb_id)
        return title

    async def ingest_movie(self, tmdb_id: int) -> IngestOutcome:
        """One film: the title row, its external ids and its artwork metadata."""
        started = time.monotonic()
        job, key = SyncResourceType.TMDB_MOVIE.value, movie_key(tmdb_id)
        self._log_start(job, key)
        title, details, outcome = await self._ensured(MediaType.MOVIE, tmdb_id)
        if title is not None and isinstance(details, TmdbMovie):
            outcome += await self._artwork_outcome(
                title, artwork_candidates(details.poster_path, details.backdrop_path)
            )
        return self._log_end(job, key, outcome, started)

    async def ingest_tv(self, tmdb_id: int) -> IngestOutcome:
        """One series: the title, every season in `seasons` including season 0, and their episodes."""
        started = time.monotonic()
        job, key = SyncResourceType.TMDB_TV.value, tv_key(tmdb_id)
        self._log_start(job, key)
        title, details, outcome = await self._ensured(MediaType.TV, tmdb_id)
        if outcome.outcome == "throttled":
            return self._log_end(job, key, outcome, started)
        if title is None or not isinstance(details, TmdbTv):
            # The series document has not moved. Only a season whose own cache term has run out is
            # refetched: TMDB's six-month cap is per resource, and the series saying nothing changed
            # does not renew a season's term.
            return self._log_end(job, key, outcome + await self._expired_seasons(tmdb_id, title), started)
        outcome += await self._stored_seasons(title, tmdb_id, details.seasons)
        outcome += await self._artwork_outcome(title, artwork_candidates(details.poster_path, details.backdrop_path))
        return self._log_end(job, key, outcome, started)

    async def ingest_artwork(
        self, title: Title, posters: Sequence[ArtworkCandidate], backdrops: Sequence[ArtworkCandidate]
    ) -> int:
        """Metadata rows for these images, one primary per kind, and bytes for the primary poster only."""
        outcome = await self._artwork_outcome(title, (list(posters), list(backdrops)))
        return outcome.inserted + outcome.updated

    # -- the provider leg ---------------------------------------------------------------------------

    async def _due(self, resource: SyncResourceType, key: str) -> bool:
        return await self._cursors.is_due(_SOURCE, resource.value, key)

    async def _season_details(self, tmdb_id: int, season_number: int) -> tuple[TmdbSeason | None, IngestOutcome]:
        """One season's episodes, and what the attempt amounted to. A refusal is never an empty season."""
        key = season_key(tmdb_id, season_number)
        if not await self._due(SyncResourceType.TMDB_SEASON, key):
            return None, IngestOutcome(skipped=1, outcome="throttled")
        try:
            details = await self._client.season_details(tmdb_id, season_number)
        except ProviderNotFoundError:
            # TMDB has no such season. That is a fact about the catalogue, not a fault, and it must never
            # be read as "this season has no episodes" - an empty list has already destroyed real data
            # elsewhere (CLAUDE.md section 9.2).
            return None, IngestOutcome(skipped=1, outcome="not-modified")
        except ProviderError:
            return None, IngestOutcome(skipped=1, outcome="failed")
        if details is None:
            return None, IngestOutcome(unchanged=1, outcome="not-modified")
        return details, IngestOutcome(outcome="fresh")

    async def _image_base_url(self) -> str:
        """TMDB's own image host, refreshed from `GET /3/configuration` and falling back to the constant."""
        if self._image_base is not None:
            return self._image_base
        if not await self._due(SyncResourceType.TMDB_CONFIGURATION, _CONFIGURATION_RESOURCE_KEY):
            # Backed off like any other leg. The constant is TMDB's own documented image base, so a
            # skipped refresh costs nothing but the chance that a host change has not been noticed yet.
            self._image_base = TMDB_IMAGE_BASE_URL
            return self._image_base
        try:
            configuration = await self._client.configuration()
        except ProviderError:
            configuration = None
        secure = None if configuration is None else configuration.images.secure_base_url
        self._image_base = secure or TMDB_IMAGE_BASE_URL
        return self._image_base

    # -- the writing leg ----------------------------------------------------------------------------

    async def _ensured(
        self, media_type: MediaType, tmdb_id: int
    ) -> tuple[Title | None, TmdbMovie | TmdbTv | None, IngestOutcome]:
        """The title row and the details it was built from, from whichever endpoint this media type has.

        The details come back too because the caller needs them for the seasons and the artwork, and
        fetching them a second time would spend the provider's budget to learn what is already in hand.
        """
        key = str(tmdb_id)
        if not await self._due(_TITLE_RESOURCE[media_type], key):
            standing = await self._standing_title(media_type, tmdb_id)
            return standing, None, IngestOutcome(skipped=1, outcome="throttled")
        details = await self._title_details(media_type, tmdb_id)
        if details is None:
            return await self._standing_title(media_type, tmdb_id), None, IngestOutcome(outcome="not-modified")
        is_movie = isinstance(details, TmdbMovie)
        values = title_values_for_movie(details) if is_movie else title_values_for_tv(details)
        title, outcome = await self._stored_title(media_type, tmdb_id, values)
        imdb = details.imdb_id if is_movie else None
        return title, details, outcome + await self._stored_external_ids(title, media_type, tmdb_id, imdb)

    async def _title_details(self, media_type: MediaType, tmdb_id: int) -> TmdbMovie | TmdbTv | None:
        """The details document, or `None` for both "nothing changed" and "nothing arrived"."""
        try:
            if media_type is MediaType.MOVIE:
                return await self._client.movie_details(tmdb_id)
            return await self._client.tv_details(tmdb_id)
        except ProviderError:
            # The client has already recorded the failure against the cursor and logged the call; the
            # ingest's job is to report that nothing arrived, not to re-raise into a nightly job.
            return None

    async def _standing_title(self, media_type: MediaType, tmdb_id: int) -> Title | None:
        return await self._session.scalar(select(Title).where(Title.media_type == media_type, Title.tmdb_id == tmdb_id))

    async def _stored_title(
        self, media_type: MediaType, tmdb_id: int, values: Mapping[str, object]
    ) -> tuple[Title, IngestOutcome]:
        """Upsert one title, writing nothing when every column already holds what the provider sent."""
        existing = (
            await self._session.execute(
                _selected(Title, ("id", *_TITLE_COLUMNS)).where(
                    Title.media_type == media_type, Title.tmdb_id == tmdb_id
                )
            )
        ).one_or_none()
        outcome = await self._written(_title_upsert(), existing, values, _TITLE_COLUMNS)
        title = await self._standing_title(media_type, tmdb_id)
        if title is None:  # pragma: no cover - the row was just written in this same transaction
            raise RuntimeError(f"the title for {media_type.value}:{tmdb_id} vanished inside one transaction")
        return title, outcome

    async def _written(
        self,
        statement: Insert,
        existing: Row[tuple[object, ...]] | None,
        values: Mapping[str, object],
        columns: Sequence[str],
    ) -> IngestOutcome:
        """One row: inserted, rewritten, or left completely alone because nothing about it moved."""
        if existing is None:
            await self._session.execute(statement, [{"id": uuid.uuid4(), **values}])
            return IngestOutcome(inserted=1, outcome="fresh")
        stored = _mapping_of(existing)
        if not changed_columns({name: stored[name] for name in columns}, {name: values[name] for name in columns}):
            return IngestOutcome(unchanged=1, outcome="not-modified")
        await self._session.execute(statement, [{"id": uuid.uuid4(), **values}])
        return IngestOutcome(updated=1, outcome="fresh")

    async def _stored_external_ids(
        self, title: Title, media_type: MediaType, tmdb_id: int, imdb_id: str | None
    ) -> IngestOutcome:
        """`tmdb` always, plus whatever `external_ids` answered with. A row already there is left alone."""
        external = await self._external_ids(media_type, tmdb_id)
        wanted: list[tuple[ExternalSource, str]] = [(ExternalSource.TMDB, str(tmdb_id))]
        imdb = (external.imdb_id if external is not None else None) or imdb_id
        if imdb:
            wanted.append((ExternalSource.IMDB, imdb))
        # The tvdb id is why this call is made at all: TheTVDB's own search ranks the One Piece anime
        # eighth, behind a live-action namesake, so the id is taken from TMDB rather than searched for.
        if external is not None and external.tvdb_id is not None:
            wanted.append((ExternalSource.TVDB, str(external.tvdb_id)))
        stored = {
            (row.source, row.value)
            for row in await self._session.execute(
                select(ExternalId.source, ExternalId.value).where(ExternalId.title_id == title.id)
            )
        }
        rows = [
            {
                "id": uuid.uuid4(),
                "entity_kind": EntityKind.TITLE,
                "source": source,
                "value": value,
                "title_id": title.id,
            }
            for source, value in ((source, _required(value, ExternalId, "value")) for source, value in wanted)
            if (source, value) not in stored
        ]
        if not rows:
            return IngestOutcome(unchanged=len(wanted), outcome="not-modified")
        # DO NOTHING as well as the read above: the read keeps the count honest, the clause keeps a
        # concurrent writer from turning an ingest into an IntegrityError.
        await self._session.execute(_external_id_upsert(), rows)
        return IngestOutcome(inserted=len(rows), unchanged=len(wanted) - len(rows), outcome="fresh")

    async def _external_ids(self, media_type: MediaType, tmdb_id: int) -> TmdbExternalIds | None:
        """The other services' ids, when the cursor is due and the upstream answered."""
        if not await self._due(SyncResourceType.TMDB_EXTERNAL_IDS, external_ids_key(media_type, tmdb_id)):
            return None
        try:
            return await self._client.external_ids(_PROVIDER_MEDIA_TYPE[media_type], tmdb_id)
        except ProviderError:
            # A film's imdb id rides on its own details payload, so a refusal here costs a tvdb id at
            # most - and the next pass, once the backoff has run out, asks again.
            return None

    async def _stored_seasons(
        self, title: Title, tmdb_id: int, summaries: Sequence[TmdbSeasonSummary]
    ) -> IngestOutcome:
        """Every season the series lists, season 0 included, and the episodes of the ones that answered."""
        outcome = IngestOutcome(outcome="not-modified")
        # Read once for the whole series rather than once per season: One Piece has 1181 episodes and
        # 24 seasons, and the per-season form would scan them twenty-four times to learn the same thing.
        known = await self._episode_index(title.id)
        fetched = 0
        for summary in summaries:
            details, attempt = await self._season_details(tmdb_id, summary.season_number)
            fetched += details is not None
            season_id, stored = await self._stored_season(title.id, summary, details)
            outcome += attempt + stored
            if details is not None:
                outcome += await self._stored_episodes(title.id, season_id, details, known)
        # A truncated fetch that reported success is worse than one that failed, so the two counts are
        # logged side by side and a reader can see the gap (CLAUDE.md section 9.2).
        self._log_pages(SyncResourceType.TMDB_SEASON.value, tv_key(tmdb_id), len(summaries), fetched)
        return outcome

    async def _stored_season(
        self, title_id: uuid.UUID, summary: TmdbSeasonSummary, details: TmdbSeason | None
    ) -> tuple[uuid.UUID, IngestOutcome]:
        values = season_values(title_id, summary, details)
        existing = (
            await self._session.execute(
                _selected(Season, ("id", *_SEASON_COLUMNS)).where(
                    Season.title_id == title_id, Season.season_number == summary.season_number
                )
            )
        ).one_or_none()
        outcome = await self._written(_season_upsert(), existing, values, _SEASON_COLUMNS)
        season_id = await self._session.scalar(
            select(Season.id).where(Season.title_id == title_id, Season.season_number == summary.season_number)
        )
        if season_id is None:  # pragma: no cover - the row was just written in this same transaction
            raise RuntimeError(f"season {summary.season_number} vanished inside one transaction")
        return season_id, outcome

    async def _episode_index(self, title_id: uuid.UUID) -> dict[int, dict[str, object]]:
        """Every episode this title already has, keyed by TMDB's own episode id, which is their unique key."""
        return {
            row.tmdb_episode_id: _mapping_of(row)
            for row in await self._session.execute(
                _selected(Episode, ("tmdb_episode_id", *_EPISODE_COLUMNS)).where(Episode.title_id == title_id)
            )
        }

    async def _stored_episodes(
        self,
        title_id: uuid.UUID,
        season_id: uuid.UUID,
        details: TmdbSeason,
        known: dict[int, dict[str, object]],
    ) -> IngestOutcome:
        """One statement for everything that moved, and no statement at all when nothing did."""
        rows, outcome = episode_rows(title_id, season_id, details.episodes, known)
        if rows:
            if not await try_episode_order_locks(self._session, (title_id,), shared=False):
                raise EpisodeOrderBusyError("Episode numbering is busy; retry the ingest.")
            await self._session.execute(_episode_upsert(), rows)
        return outcome

    async def _expired_seasons(self, tmdb_id: int, title: Title | None) -> IngestOutcome:
        """The seasons whose own six-month caching term has run out, when the series itself has not moved."""
        if title is None:
            return IngestOutcome(outcome="not-modified")
        numbers = list(await self._session.scalars(select(Season.season_number).where(Season.title_id == title.id)))
        expired = await self._expired_season_numbers(tmdb_id, numbers)
        if not expired:
            return IngestOutcome(unchanged=1, outcome="not-modified")
        outcome = IngestOutcome(outcome="not-modified")
        known = await self._episode_index(title.id)
        for number in expired:
            details, attempt = await self._season_details(tmdb_id, number)
            outcome += attempt
            if details is None:
                continue
            season_id = await self._session.scalar(
                select(Season.id).where(Season.title_id == title.id, Season.season_number == number)
            )
            if season_id is not None:
                outcome += await self._stored_episodes(title.id, season_id, details, known)
        return outcome

    async def _expired_season_numbers(self, tmdb_id: int, numbers: Sequence[int]) -> list[int]:
        """Which of these seasons' cursors have reached TMDB's six-month cap, in one query rather than N.

        The cutoff is `sync_cursor.ceiling_cutoff`, so the predicate this `IN` expresses and the one
        `success_past_ceiling` computes stay the same rule. A cursor that has never succeeded is absent by
        construction: `NULL` satisfies no comparison, and it is caching nothing whose term could run out.
        """
        by_key = {season_key(tmdb_id, number): number for number in numbers}
        if not by_key:
            return []
        reached = await self._session.scalars(
            select(SyncState.resource_key).where(
                SyncState.source == ExternalSource.TMDB,
                SyncState.resource_type == SyncResourceType.TMDB_SEASON,
                SyncState.resource_key.in_(list(by_key)),
                SyncState.last_success_at <= ceiling_cutoff(self._clock(), TMDB_CACHE_CEILING_DAYS),
            )
        )
        return sorted(by_key[key] for key in reached)

    # -- artwork ------------------------------------------------------------------------------------

    async def _artwork_outcome(
        self, title: Title, candidates: tuple[list[ArtworkCandidate], list[ArtworkCandidate]]
    ) -> IngestOutcome:
        posters, backdrops = candidates
        everything = [*posters, *backdrops]
        if not everything:
            return IngestOutcome(outcome="not-modified")
        outcome = await self._stored_artwork(title, everything)
        for kind, group in ((ArtworkKind.POSTER, posters), (ArtworkKind.BACKDROP, backdrops)):
            chosen = primary_candidate(group, title.original_language)
            if chosen is not None:
                outcome += await self._made_primary(title.id, kind, chosen.remote_path)
        await self._cached_bytes(title, primary_candidate(posters, title.original_language))
        return outcome

    async def _stored_artwork(self, title: Title, candidates: Sequence[ArtworkCandidate]) -> IngestOutcome:
        stored = {
            row.remote_path: _mapping_of(row)
            for row in await self._session.execute(
                _selected(Artwork, ("remote_path", *_ARTWORK_COLUMNS)).where(
                    Artwork.title_id == title.id, Artwork.source == ExternalSource.TMDB
                )
            )
        }
        rows: list[dict[str, object]] = []
        outcome = IngestOutcome(outcome="not-modified")
        for candidate in candidates:
            values = artwork_values(title.id, candidate)
            existing = stored.get(candidate.remote_path)
            comparable = {name: values[name] for name in _ARTWORK_COLUMNS}
            if existing is not None and not changed_columns(existing, comparable):
                outcome += IngestOutcome(unchanged=1, outcome="not-modified")
                continue
            rows.append({"id": uuid.uuid4(), **values})
            outcome += IngestOutcome(inserted=int(existing is None), updated=int(existing is not None), outcome="fresh")
        if rows:
            await self._session.execute(_artwork_upsert(), rows)
        return outcome

    async def _made_primary(self, title_id: uuid.UUID, kind: ArtworkKind, remote_path: str) -> IngestOutcome:
        """One primary per kind per title. The others are cleared first: the index is not deferrable."""
        await self._session.execute(
            update(Artwork)
            .where(
                Artwork.title_id == title_id,
                Artwork.kind == kind,
                Artwork.is_primary.is_(True),
                Artwork.remote_path != remote_path,
            )
            .values(is_primary=False)
        )
        await self._session.execute(
            update(Artwork)
            .where(
                Artwork.title_id == title_id,
                Artwork.kind == kind,
                Artwork.remote_path == remote_path,
                Artwork.is_primary.is_(False),
            )
            .values(is_primary=True)
        )
        return IngestOutcome(outcome="not-modified")

    async def _cached_bytes(self, title: Title, chosen: ArtworkCandidate | None) -> None:
        """The primary poster's bytes, on disk under `heroes_dir`. Never the backdrops, never in Postgres."""
        if self._artwork is None or chosen is None:
            return
        row = await self._session.scalar(
            select(Artwork).where(
                Artwork.title_id == title.id,
                Artwork.source == ExternalSource.TMDB,
                Artwork.remote_path == chosen.remote_path,
            )
        )
        if row is None:  # pragma: no cover - written moments ago in this same transaction
            return
        await self._artwork.ensure_cached(row, secure_base_url=await self._image_base_url(), size=TMDB_POSTER_SIZE)

    # -- logging ------------------------------------------------------------------------------------

    def _log_start(self, job: str, resource: str) -> None:
        _LOGGER.info("ingest_start job=%s source=%s resource=%s", job, _SOURCE, resource)

    def _log_end(self, job: str, resource: str, outcome: IngestOutcome, started: float) -> IngestOutcome:
        """The end record every pass writes, zeros included: a run that changed nothing must say so."""
        _LOGGER.info(
            "ingest_end job=%s source=%s resource=%s inserted=%d updated=%d unchanged=%d skipped=%d"
            " elapsed_ms=%d outcome=%s",
            job,
            _SOURCE,
            resource,
            outcome.inserted,
            outcome.updated,
            outcome.unchanged,
            outcome.skipped,
            int((time.monotonic() - started) * 1000),
            outcome.outcome,
        )
        return outcome

    def _log_pages(self, job: str, resource: str, listed: int, fetched: int) -> None:
        _LOGGER.info(
            "ingest_pages job=%s source=%s resource=%s listed=%d fetched=%d", job, _SOURCE, resource, listed, fetched
        )
