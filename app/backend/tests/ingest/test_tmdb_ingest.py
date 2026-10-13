"""The TMDB ingest: what a recorded payload becomes in Postgres, and what a second pass does not touch.

Two halves. The pure half - the minutes-to-seconds conversion, the row projections, the change set, the
primary-artwork choice, the cursor keys, the SQL each upsert compiles to - runs anywhere. The half that
writes runs against a real Postgres and skips loudly without one; a mocked database would prove only that
the mock agrees with itself (CLAUDE.md section 16.4).

Provider traffic is recorded fixtures through an `httpx.MockTransport`. Nothing here reaches a network.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from collections.abc import Iterator, Mapping
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Final

import httpx
import pytest
from mock_responder import MockResponder
from pydantic import SecretStr
from sample_images import PNG
from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from provider_fixtures import (
    A_BURST_NO_TEST_EXHAUSTS,
    RECORDED_TOKEN,
    TMDB,
    RecordingResponseCache,
    fixture_headers,
    fixture_json,
    tmdb_client_for,
)
from provider_fixtures import fixture_bytes as recorded_bytes
from statement_support import counted_statements
from tv_watchlist.clients.rate_limiter import TokenBucket
from tv_watchlist.clients.tmdb_client import TmdbClient
from tv_watchlist.clients.transport import build_provider_http
from tv_watchlist.clock import utcnow
from tv_watchlist.config import Settings
from tv_watchlist.constants import (
    TMDB_API_BASE_URL,
    TMDB_CACHE_CEILING_DAYS,
    TMDB_POSTER_SIZE,
    TMDB_REQUESTS_PER_SECOND,
)
from tv_watchlist.data.enums import ArtworkKind, EntityKind, ExternalSource, MediaType
from tv_watchlist.data.models import Artwork, Episode, ExternalId, Season, SyncState, Title
from tv_watchlist.ingest.artwork_candidate import ArtworkCandidate
from tv_watchlist.ingest.ingest_outcome import IngestOutcome
from tv_watchlist.ingest.sync_cursor import PostgresResponseCache
from tv_watchlist.ingest.tmdb_ingest import (
    TmdbIngest,
    artwork_candidates,
    artwork_values,
    changed_columns,
    episode_rows,
    episode_values,
    external_ids_key,
    minutes_to_seconds,
    movie_key,
    primary_candidate,
    season_key,
    season_values,
    title_values_for_movie,
    title_values_for_tv,
    tmdb_date,
    tv_key,
)
from tv_watchlist.models.tmdb.tmdb_movie import TmdbMovie
from tv_watchlist.models.tmdb.tmdb_season import TmdbSeason
from tv_watchlist.models.tmdb.tmdb_tv import TmdbTv
from tv_watchlist.services.artwork_cache import ArtworkCache
from tv_watchlist.services.tmdb_key import tmdb_key

ONE_PIECE: Final[int] = 37854
INUYASHA: Final[int] = 35610
ATTACK_OF_THE_CLONES: Final[int] = 1894
# The episode the reference assertions hang on: One Piece's Laboon, absolute-numbered 62 inside season 2.
LABOON_AIR_DATE: Final[date] = date(2001, 3, 21)
LABOON_EPISODE_NUMBER: Final[int] = 62
SEASON_TWO_NUMBERS: Final[list[int]] = list(range(62, 78))
# `tv_37854.json` at capture: 23 regular seasons, a 24th entry for the specials bucket, 1181 episodes.
ONE_PIECE_SEASON_ROWS: Final[int] = 24
ONE_PIECE_SEASON_COUNT: Final[int] = 23
ONE_PIECE_EPISODE_COUNT: Final[int] = 1181
# Only seasons 0, 1 and 2 were recorded; the rest answer 404, which is a skip, not a failure.
RECORDED_SEASONS: Final[tuple[int, ...]] = (0, 1, 2)

# A literal address, so composing an image URL never asks a resolver anything - see the cache tests.
AN_IMAGE_HOST: Final[str] = "https://93.184.216.34/t/p/"
A_POSTER_PATH: Final[str] = "/dB4EDhre2dsC2kxYDavyKWqLQwi.jpg"
ANOTHER_POSTER_PATH: Final[str] = "/6fRwRD7GdCfg6owzmCT3VgQtowl.jpg"


class RoutingResponder:
    """Answers by path from recorded bodies, and 404s anything that was never recorded.

    Ordered canned responses cannot drive an ingest: one pass makes a series call, an external-ids call
    and one call per season, and only three of One Piece's twenty-four seasons were ever captured.
    """

    def __init__(self, routes: Mapping[str, str], *, overrides: Mapping[str, httpx.Response] | None = None) -> None:
        self._routes = dict(routes)
        self._overrides = dict(overrides or {})
        self.requested: list[str] = []
        self.transport = httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.requested.append(path)
        override = self._overrides.get(path)
        if override is not None:
            return httpx.Response(override.status_code, content=override.content, headers=override.headers)
        name = self._routes.get(path)
        if name is None:
            return httpx.Response(404, json={"status_code": 34, "status_message": "resource not found"})
        return httpx.Response(200, content=recorded_bytes(TMDB, name), headers=fixture_headers(TMDB, name))


def tv_routes(tmdb_id: int, stem: str, seasons: tuple[int, ...]) -> dict[str, str]:
    """Every path one series ingest can hit that a fixture was recorded for."""
    routes = {f"/3/tv/{tmdb_id}": stem, f"/3/tv/{tmdb_id}/external_ids": f"{stem}_external_ids"}
    return routes | {f"/3/tv/{tmdb_id}/season/{number}": f"{stem}_season_{number}" for number in seasons}


def client_over(responder: RoutingResponder, session: AsyncSession) -> TmdbClient:
    """A real `TmdbClient` on recorded answers and the ingest's own cursor table."""
    http = build_provider_http(TMDB_API_BASE_URL, headers={"Accept": "application/json"}, transport=responder.transport)
    return TmdbClient(
        SecretStr(RECORDED_TOKEN),
        http=http,
        bucket=TokenBucket(TMDB_REQUESTS_PER_SECOND, A_BURST_NO_TEST_EXHAUSTS),
        cache=PostgresResponseCache(session),
    )


def one_piece_ingest(session: AsyncSession) -> tuple[TmdbIngest, RoutingResponder]:
    responder = RoutingResponder(tv_routes(ONE_PIECE, "tv_37854", RECORDED_SEASONS))
    return TmdbIngest(session, client_over(responder, session)), responder


@pytest.fixture
def episode_statements(engine: AsyncEngine) -> Iterator[list[str]]:
    """Statements naming `episode` - never `episode_order`, which `\\b` keeps out."""
    with counted_statements(engine, "episode") as seen:
        yield seen


# -- fixture readers, above their first use: parametrize calls them at collection time ---------------


def _configuration_on(image_host: str) -> httpx.Response:
    """The recorded configuration with its image host swapped for a literal address."""
    recorded = fixture_json(TMDB, "configuration")
    images = recorded["images"]
    assert isinstance(images, dict)
    patched = {**recorded, "images": {**images, "secure_base_url": image_host}}
    return httpx.Response(200, content=json.dumps(patched).encode())


def _recorded_response(name: str) -> httpx.Response:
    return httpx.Response(200, content=recorded_bytes(TMDB, name), headers=fixture_headers(TMDB, name))


def _movie_model() -> TmdbMovie:
    return TmdbMovie.model_validate(fixture_json(TMDB, "movie_attack_of_the_clones"))


def _tv_model(tmdb_id: int) -> TmdbTv:
    return TmdbTv.model_validate(fixture_json(TMDB, f"tv_{tmdb_id}"))


def _season_model(tmdb_id: int, season_number: int) -> TmdbSeason:
    return TmdbSeason.model_validate(fixture_json(TMDB, f"tv_{tmdb_id}_season_{season_number}"))


def _candidate(remote_path: str, *, language: str | None, vote: Decimal | None) -> ArtworkCandidate:
    return ArtworkCandidate(kind=ArtworkKind.POSTER, remote_path=remote_path, language=language, vote_average=vote)


async def _the_title(session: AsyncSession, tmdb_id: int, *, media_type: MediaType = MediaType.TV) -> Title:
    return (await session.scalars(select(Title).where(Title.media_type == media_type, Title.tmdb_id == tmdb_id))).one()


# ---------------------------------------------------------------------------------------------------
# The pure half: no database, no network.
# ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("minutes", "seconds"),
    [(142, 8520), (24, 1440), (1, 60), (None, None), (0, None), (-5, None)],
)
def test_minutes_become_seconds_or_nothing(minutes: int | None, seconds: int | None) -> None:
    """`0` becomes `None`, not `0`: every duration column carries `CHECK runtime_seconds > 0`."""
    assert minutes_to_seconds(minutes) == seconds


def test_runtime_minutes_become_seconds_exactly_once() -> None:
    """Reference value: the recorded film's own `runtime`, in minutes, times sixty and no more."""
    recorded = fixture_json(TMDB, "movie_attack_of_the_clones")
    runtime_minutes = recorded["runtime"]
    assert isinstance(runtime_minutes, int)

    values = title_values_for_movie(_movie_model())

    assert values["runtime_seconds"] == runtime_minutes * 60
    # The second application a reader would fear: seconds fed back in would be an hour times bigger.
    assert minutes_to_seconds(values["runtime_seconds"]) != values["runtime_seconds"]


def test_an_episode_without_a_runtime_stores_none() -> None:
    episode = _season_model(ONE_PIECE, 2).episodes[0]
    without = episode.model_copy(update={"runtime": None})

    assert episode_values(uuid.uuid4(), uuid.uuid4(), episode)["runtime_seconds"] == episode.runtime * 60
    assert episode_values(uuid.uuid4(), uuid.uuid4(), without)["runtime_seconds"] is None


@pytest.mark.parametrize(
    ("raw", "parsed"),
    [
        ("2001-03-21", date(2001, 3, 21)),
        ("1999-10-20", date(1999, 10, 20)),
        ("", None),
        (None, None),
        ("nonsense", None),
        ("2001-13-99", None),
        ("not-a-date", None),
    ],
)
def test_a_tmdb_date_string_becomes_a_date_or_nothing(raw: str | None, parsed: date | None) -> None:
    """TMDB sends `""` for an undated work, which is absent rather than a parse failure."""
    assert tmdb_date(raw) == parsed


def test_the_cursor_keys_are_the_shapes_the_client_writes() -> None:
    """Built here because the gate reads them; the round-trip against a real fetch is asserted below."""
    assert movie_key(ATTACK_OF_THE_CLONES) == str(ATTACK_OF_THE_CLONES)
    assert tv_key(ONE_PIECE) == str(ONE_PIECE)
    assert season_key(ONE_PIECE, 0) == f"{ONE_PIECE}/0"
    assert external_ids_key(MediaType.TV, ONE_PIECE) == f"tv/{ONE_PIECE}"
    assert external_ids_key(MediaType.MOVIE, ATTACK_OF_THE_CLONES) == f"movie/{ATTACK_OF_THE_CLONES}"


def test_a_details_document_offers_at_most_one_poster_and_one_backdrop() -> None:
    movie = _movie_model()

    posters, backdrops = artwork_candidates(movie.poster_path, movie.backdrop_path)

    assert [candidate.remote_path for candidate in posters] == [movie.poster_path]
    assert [candidate.kind for candidate in backdrops] == [ArtworkKind.BACKDROP]
    assert artwork_candidates(None, None) == ([], [])


def test_a_title_with_no_language_of_its_own_still_gets_a_primary() -> None:
    """`original_language` is nullable, and a `None` there must not skip straight past the English pass."""
    english = _candidate("/en.jpg", language="en", vote=Decimal("3.0"))
    other = _candidate("/xx.jpg", language="xx", vote=Decimal("9.0"))

    assert primary_candidate([english, other], None) is english
    assert primary_candidate([other], None) is other


def test_a_provider_string_is_clipped_to_the_width_its_column_declares() -> None:
    """A value one character over the declared width aborts the transaction, so it is cut at the boundary."""
    long_title = "A" * 900
    recorded = fixture_json(TMDB, "tv_37854")
    values = title_values_for_tv(TmdbTv.model_validate({**recorded, "name": long_title}))

    assert len(str(values["name"])) == Title.__table__.columns["name"].type.length
    assert len(str(values["match_key"])) <= Title.__table__.columns["match_key"].type.length


def test_a_series_stores_no_title_runtime() -> None:
    """`episode_run_time` is a per-episode figure; storing it as the title's would corrupt every sum."""
    values = title_values_for_tv(_tv_model(ONE_PIECE))

    assert values["runtime_seconds"] is None
    assert values["season_count"] == ONE_PIECE_SEASON_COUNT
    assert values["episode_count"] == ONE_PIECE_EPISODE_COUNT
    assert values["media_type"] is MediaType.TV
    assert values["original_language"] == "ja"


def test_a_title_carries_the_resolver_key_the_workbook_side_will_match_on() -> None:
    movie = title_values_for_movie(_movie_model())

    # The resolver mints it; the ingest must not invent a second normalisation.
    assert movie["match_key"] == "star wars episode 2 attack of the clones 2002"


@pytest.mark.parametrize(
    ("existing", "values", "changed"),
    [
        ({"name": "One Piece"}, {"name": "One Piece"}, {}),
        ({"name": "One Piece"}, {"name": "ONE PIECE"}, {"name": "ONE PIECE"}),
        ({"name": None}, {"name": "One Piece"}, {"name": "One Piece"}),
        ({"runtime_seconds": 1440}, {"runtime_seconds": 1440}, {}),
        ({"a": 1, "b": 2}, {"a": 1, "b": 3}, {"b": 3}),
    ],
)
def test_only_the_columns_that_actually_moved_are_written(
    existing: dict[str, object], values: dict[str, object], changed: dict[str, object]
) -> None:
    """An unchanged row produces no statement at all, which is what keeps `updated_at` still."""
    assert changed_columns(existing, values) == changed


def test_the_primary_poster_prefers_the_titles_own_language_then_english() -> None:
    japanese = _candidate("/ja.jpg", language="ja", vote=Decimal("5.0"))
    english = _candidate("/en.jpg", language="en", vote=Decimal("9.0"))
    languageless = _candidate("/none.jpg", language=None, vote=Decimal("10.0"))

    assert primary_candidate([japanese, english, languageless], "ja") is japanese
    assert primary_candidate([english, languageless], "ja") is english
    assert primary_candidate([languageless], "ja") is languageless
    assert primary_candidate([], "ja") is None


def test_the_primary_poster_breaks_a_language_tie_on_the_highest_vote() -> None:
    low = _candidate("/low.jpg", language="en", vote=Decimal("4.0"))
    high = _candidate("/high.jpg", language="en", vote=Decimal("8.5"))
    unvoted = _candidate("/unvoted.jpg", language="en", vote=None)

    assert primary_candidate([low, high, unvoted], "en") is high
    assert primary_candidate([unvoted, low], "en") is low


async def test_the_ingest_and_the_client_agree_on_a_seasons_cursor_key() -> None:
    """The gate reads the cursor the client writes, so the two key builders must not drift apart."""
    cache = RecordingResponseCache()
    client, _ = tmdb_client_for(_recorded_response("tv_37854_season_2"), cache=cache)

    await client.season_details(ONE_PIECE, 2)

    assert cache.stored[-1].resource_key == season_key(ONE_PIECE, 2)
    assert cache.stored[-1].resource_type == "tmdb_season"


def test_every_upsert_compiles_for_postgres() -> None:
    """The DB half only runs in CI, so the statements are proved to be real Postgres here."""
    dialect = postgresql.dialect()
    compiled = [str(statement.compile(dialect=dialect)) for statement in TmdbIngest.upsert_shapes()]

    assert len(compiled) == 5
    assert all("ON CONFLICT" in sql for sql in compiled)
    assert any("DO NOTHING" in sql for sql in compiled)
    # No literal ever reaches the SQL text: every value is a bound parameter (CLAUDE.md B13).
    assert not any("'" in sql.split("ON CONFLICT")[0] for sql in compiled)


def _projected_rows() -> list[tuple[str, dict[str, object]]]:
    """One realistic row per table, built from the recorded fixtures the ingest would really see."""
    title_id, season_id = uuid.uuid4(), uuid.uuid4()
    return [
        ("title", title_values_for_movie(_movie_model())),
        ("title", title_values_for_tv(_tv_model(ONE_PIECE))),
        (
            "season",
            season_values(title_id, _tv_model(ONE_PIECE).seasons[2], _season_model(ONE_PIECE, 2)),
        ),
        ("season", season_values(title_id, _tv_model(ONE_PIECE).seasons[0])),
        ("episode", episode_values(title_id, season_id, _season_model(ONE_PIECE, 2).episodes[0])),
        ("episode", episode_values(title_id, season_id, _season_model(ONE_PIECE, 0).episodes[0])),
        ("artwork", artwork_values(title_id, _candidate(A_POSTER_PATH, language="ja", vote=Decimal("7.24")))),
        (
            "external_id",
            {
                "entity_kind": EntityKind.TITLE,
                "source": ExternalSource.TVDB,
                "value": "81797",
                "title_id": title_id,
            },
        ),
    ]


_MODELS: Final[dict[str, type[object]]] = {
    "title": Title,
    "season": Season,
    "episode": Episode,
    "external_id": ExternalId,
    "artwork": Artwork,
}


@pytest.mark.parametrize(("table", "values"), _projected_rows(), ids=lambda value: getattr(value, "__name__", None))
def test_every_projected_row_fits_the_table_it_is_written_to(table: str, values: dict[str, object]) -> None:
    """The DB half only runs in CI, so the column names and the NOT NULLs are checked against the schema here."""
    columns = _MODELS[table].__table__.columns
    required = {
        name
        for name, column in columns.items()
        if not column.nullable and column.default is None and column.server_default is None
    }

    assert set(values) <= set(columns.keys())
    # `id` is minted at the call site, not by the projection, and every other default is the schema's.
    assert required <= set(values)
    for name, value in values.items():
        declared = getattr(columns[name].type, "length", None)
        assert declared is None or not isinstance(value, str) or len(value) <= declared


@pytest.mark.parametrize(("table", "values"), _projected_rows(), ids=lambda value: getattr(value, "__name__", None))
def test_every_projected_row_satisfies_its_tables_check_constraints(table: str, values: dict[str, object]) -> None:
    """`CHECK runtime_seconds > 0` and the non-negative numbers, asserted where a database is not available."""
    for name in ("runtime_seconds",):
        stored = values.get(name)
        assert stored is None or (isinstance(stored, int) and stored > 0)
    for name in ("season_number", "episode_number", "episode_count", "season_count", "width", "height"):
        stored = values.get(name)
        assert stored is None or (isinstance(stored, int) and stored >= 0)


def test_every_upsert_compiles_with_the_rows_the_ingest_actually_builds() -> None:
    """The executemany compile path, with the exact key set each statement is executed with."""
    dialect = postgresql.dialect()
    by_table = {statement.table.name: statement for statement in TmdbIngest.upsert_shapes()}

    for table, values in _projected_rows():
        row = {"id": uuid.uuid4(), **values}
        compiled = str(by_table[table].compile(dialect=dialect, column_keys=sorted(row)))
        assert compiled.startswith(f"INSERT INTO {table} ")
        for name in row:
            assert f"%({name})s" in compiled


def test_the_end_record_of_a_pass_that_changed_nothing_still_says_so(caplog: pytest.LogCaptureFixture) -> None:
    """A run that wrote nothing must log that it wrote nothing: no output is not a result (CLAUDE.md 9.2)."""
    client, _ = tmdb_client_for(_recorded_response("configuration"))
    ingest = TmdbIngest(AsyncSession(), client)

    with caplog.at_level(logging.INFO, logger="tv_watchlist.ingest.tmdb_ingest"):
        ingest._log_start("tmdb_tv", tv_key(ONE_PIECE))
        returned = ingest._log_end("tmdb_tv", tv_key(ONE_PIECE), IngestOutcome(), time.monotonic())

    assert caplog.records[0].getMessage().startswith("ingest_start ")
    record = caplog.records[-1].getMessage()
    assert returned == IngestOutcome()
    assert "inserted=0" in record
    assert "updated=0" in record
    assert "unchanged=0" in record
    assert "skipped=0" in record
    assert "outcome=not-modified" in record
    assert re.search(r"\belapsed_ms=\d+\b", record) is not None
    assert f"resource={tv_key(ONE_PIECE)}" in record
    assert "\n" not in record and "\r" not in record


def test_a_partial_fetch_is_logged_beside_what_it_was_supposed_to_be(caplog: pytest.LogCaptureFixture) -> None:
    """A truncated fetch reporting success is worse than one that failed, so the gap is on the record."""
    client, _ = tmdb_client_for(_recorded_response("configuration"))
    ingest = TmdbIngest(AsyncSession(), client)

    with caplog.at_level(logging.INFO, logger="tv_watchlist.ingest.tmdb_ingest"):
        ingest._log_pages("tmdb_season", tv_key(ONE_PIECE), ONE_PIECE_SEASON_ROWS, len(RECORDED_SEASONS))

    record = caplog.records[-1].getMessage()
    assert f"listed={ONE_PIECE_SEASON_ROWS}" in record
    assert f"fetched={len(RECORDED_SEASONS)}" in record
    assert "\n" not in record and "\r" not in record


def test_a_clip_that_actually_drops_characters_says_which_column_it_happened_to(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Ruling 32: `match_key` stays String(255), so the truncation has to leave evidence behind."""
    recorded = fixture_json(TMDB, "tv_37854")
    limit = Title.__table__.columns["match_key"].type.length

    with caplog.at_level(logging.INFO, logger="tv_watchlist.ingest.tmdb_ingest"):
        short = title_values_for_tv(TmdbTv.model_validate(recorded))
        quiet = len(caplog.records)
        clipped = title_values_for_tv(TmdbTv.model_validate({**recorded, "name": "A " * 400}))

    assert quiet == 0, "a name that fits must log nothing at all"
    assert len(str(short["match_key"])) <= limit
    assert len(str(clipped["match_key"])) == limit
    clips = [record.getMessage() for record in caplog.records if record.getMessage().startswith("clipped ")]
    assert any("column=match_key from=" in message and f"to={limit}" in message for message in clips)
    assert all("table=title" in message for message in clips)


def test_an_episode_id_seen_under_two_seasons_of_one_pass_is_an_update_not_a_second_insert() -> None:
    """`tmdb_episode_id` is unique table-wide, and Postgres refuses two of them in one ON CONFLICT."""
    title_id, first_season, second_season = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    episode = _season_model(ONE_PIECE, 2).episodes[0]
    known: dict[int, dict[str, object]] = {}

    first_rows, first = episode_rows(title_id, first_season, [episode], known)
    second_rows, second = episode_rows(title_id, second_season, [episode], known)

    assert first == IngestOutcome(inserted=1, outcome="fresh")
    # TMDB re-parented it: the same episode, a different season, so the row is rewritten rather than added.
    assert second == IngestOutcome(updated=1, outcome="fresh")
    assert [row["season_id"] for row in first_rows] == [first_season]
    assert [row["season_id"] for row in second_rows] == [second_season]
    assert known[episode.id]["season_id"] == second_season


def test_an_episode_id_repeated_inside_one_season_is_queued_only_once() -> None:
    """Two rows carrying one conflict key in a single statement is a refusal, not an update."""
    episode = _season_model(ONE_PIECE, 2).episodes[0]
    known: dict[int, dict[str, object]] = {}

    rows, outcome = episode_rows(uuid.uuid4(), uuid.uuid4(), [episode, episode], known)

    assert len(rows) == 1
    assert outcome == IngestOutcome(inserted=1, skipped=1, outcome="fresh")


def test_a_season_whose_episodes_have_not_moved_produces_no_rows_at_all() -> None:
    """The zero-update guarantee, proved on the decision rather than only through Postgres."""
    title_id, season_id = uuid.uuid4(), uuid.uuid4()
    episodes = _season_model(ONE_PIECE, 2).episodes
    known: dict[int, dict[str, object]] = {}

    episode_rows(title_id, season_id, episodes, known)
    rows, outcome = episode_rows(title_id, season_id, episodes, known)

    assert rows == []
    assert outcome == IngestOutcome(unchanged=len(episodes), outcome="not-modified")


def test_an_outcome_merges_its_counts_and_reports_the_loudest_result() -> None:
    fresh = IngestOutcome(inserted=2, outcome="fresh")
    skipped = IngestOutcome(skipped=1, outcome="throttled")
    failed = IngestOutcome(skipped=1, outcome="failed")

    assert fresh + skipped == IngestOutcome(inserted=2, skipped=1, outcome="fresh")
    assert fresh + failed == IngestOutcome(inserted=2, skipped=1, outcome="failed")
    assert IngestOutcome() + IngestOutcome() == IngestOutcome(outcome="not-modified")


# ---------------------------------------------------------------------------------------------------
# The half that writes. Skips loudly without a Postgres; runs for real in CI.
# ---------------------------------------------------------------------------------------------------


async def test_ingesting_one_piece_writes_24_seasons_including_the_specials_bucket(db_session: AsyncSession) -> None:
    ingest, _ = one_piece_ingest(db_session)

    outcome = await ingest.ingest_tv(ONE_PIECE)
    await db_session.flush()

    title = await _the_title(db_session, ONE_PIECE)
    seasons = list(await db_session.scalars(select(Season.season_number).where(Season.title_id == title.id)))
    assert sorted(seasons) == list(range(ONE_PIECE_SEASON_ROWS))
    assert 0 in seasons
    assert title.season_count == ONE_PIECE_SEASON_COUNT
    assert title.episode_count == ONE_PIECE_EPISODE_COUNT
    # The twenty-one seasons no fixture was recorded for are skipped, never mistaken for empty ones.
    assert outcome.skipped == ONE_PIECE_SEASON_ROWS - len(RECORDED_SEASONS)
    assert outcome.outcome == "fresh"


async def test_season_two_episode_numbers_are_stored_as_62_to_77_not_1_to_16(db_session: AsyncSession) -> None:
    """Reference value: TMDB numbers anime absolutely inside season buckets, and nothing renumbers it."""
    ingest, _ = one_piece_ingest(db_session)

    await ingest.ingest_tv(ONE_PIECE)
    await db_session.flush()

    numbers = list(
        await db_session.scalars(
            select(Episode.episode_number)
            .join(Title, Title.id == Episode.title_id)
            .where(Title.tmdb_id == ONE_PIECE, Episode.season_number == 2)
            .order_by(Episode.episode_number)
        )
    )
    assert numbers == SEASON_TWO_NUMBERS


async def test_laboon_carries_the_canonical_pointer(db_session: AsyncSession) -> None:
    ingest, _ = one_piece_ingest(db_session)

    await ingest.ingest_tv(ONE_PIECE)
    await db_session.flush()

    # Keyed on the episode number the pointer itself names. The air date does NOT identify one episode:
    # 62 and 63 are a double-length broadcast and share it, which is ordinary for this series.
    laboon = (
        await db_session.scalars(
            select(Episode)
            .join(Title, Title.id == Episode.title_id)
            .where(Title.tmdb_id == ONE_PIECE, Episode.episode_number == LABOON_EPISODE_NUMBER)
        )
    ).one()
    key = tmdb_key(MediaType.TV, ONE_PIECE, season_number=laboon.season_number, episode_number=laboon.episode_number)

    assert laboon.air_date == LABOON_AIR_DATE
    assert key == f"tv:{ONE_PIECE}:s2:e{LABOON_EPISODE_NUMBER}"


async def test_a_film_runtime_is_stored_in_seconds(db_session: AsyncSession) -> None:
    responder = RoutingResponder({f"/3/movie/{ATTACK_OF_THE_CLONES}": "movie_attack_of_the_clones"})
    ingest = TmdbIngest(db_session, client_over(responder, db_session))
    recorded = fixture_json(TMDB, "movie_attack_of_the_clones")

    await ingest.ingest_movie(ATTACK_OF_THE_CLONES)
    await db_session.flush()

    title = await _the_title(db_session, ATTACK_OF_THE_CLONES, media_type=MediaType.MOVIE)
    assert title.runtime_seconds == recorded["runtime"] * 60
    # A film's imdb id rides on its own details payload, so a 404 on `external_ids` loses nothing.
    values = set(
        await db_session.scalars(
            select(ExternalId.value).where(ExternalId.title_id == title.id, ExternalId.source == ExternalSource.IMDB)
        )
    )
    assert values == {recorded["imdb_id"]}


async def test_episode_title_id_equals_its_seasons_title_id_for_every_episode(db_session: AsyncSession) -> None:
    """A CHECK cannot express a cross-table invariant, so the suite is where it is asserted."""
    ingest, _ = one_piece_ingest(db_session)

    await ingest.ingest_tv(ONE_PIECE)
    await db_session.flush()

    mismatched = await db_session.scalar(
        select(func.count())
        .select_from(Episode)
        .join(Season, Season.id == Episode.season_id)
        .where(Episode.title_id != Season.title_id)
    )
    total = await db_session.scalar(select(func.count()).select_from(Episode))
    assert mismatched == 0
    assert total > 0


async def test_external_ids_land_as_typed_rows_on_the_title(db_session: AsyncSession) -> None:
    ingest, _ = one_piece_ingest(db_session)
    recorded = fixture_json(TMDB, "tv_37854_external_ids")

    await ingest.ingest_tv(ONE_PIECE)
    await db_session.flush()

    title = await _the_title(db_session, ONE_PIECE)
    rows = list(
        await db_session.execute(
            select(ExternalId.source, ExternalId.value, ExternalId.entity_kind).where(ExternalId.title_id == title.id)
        )
    )
    assert (ExternalSource.TVDB, str(recorded["tvdb_id"]), EntityKind.TITLE) in rows
    assert (ExternalSource.TMDB, str(ONE_PIECE), EntityKind.TITLE) in rows
    assert (ExternalSource.IMDB, recorded["imdb_id"], EntityKind.TITLE) in rows

    second, _ = one_piece_ingest(db_session)
    await second.ingest_tv(ONE_PIECE)
    await db_session.flush()
    again = list(await db_session.scalars(select(ExternalId.value).where(ExternalId.title_id == title.id)))
    assert len(again) == len(rows)


async def test_a_second_ingest_with_an_equal_digest_updates_zero_rows(
    db_session: AsyncSession, episode_statements: list[str]
) -> None:
    """The digest short-circuit: identical bytes mean nothing below the title is rewritten."""
    ingest, _ = one_piece_ingest(db_session)
    await ingest.ingest_tv(ONE_PIECE)
    await db_session.flush()
    # `dict(result)` would take the MAPPING path - a Result has `.keys()` but no `__getitem__` - so the
    # rows are asked for explicitly.
    stamps = dict((await db_session.execute(select(Episode.id, Episode.updated_at))).all())
    assert stamps

    episode_statements.clear()
    second, _ = one_piece_ingest(db_session)
    outcome = await second.ingest_tv(ONE_PIECE)
    await db_session.flush()

    assert outcome.outcome == "not-modified"
    assert dict((await db_session.execute(select(Episode.id, Episode.updated_at))).all()) == stamps
    assert [sql for sql in episode_statements if sql.lower().lstrip().startswith(("update", "insert"))] == []


async def test_a_not_modified_title_never_touches_its_episodes(
    db_session: AsyncSession, episode_statements: list[str]
) -> None:
    """A 304 answers the series call, so the season calls are never made and no episode row is touched."""
    cursors = PostgresResponseCache(db_session)
    await cursors.store(
        ExternalSource.TMDB.value,
        "tmdb_tv",
        str(ONE_PIECE),
        etag=fixture_headers(TMDB, "tv_37854")["etag"],
        last_modified=None,
        payload_digest="a digest nothing will match",
    )
    responder = RoutingResponder({}, overrides={f"/3/tv/{ONE_PIECE}": httpx.Response(304)})
    ingest = TmdbIngest(db_session, client_over(responder, db_session))

    episode_statements.clear()
    outcome = await ingest.ingest_tv(ONE_PIECE)

    assert outcome.outcome == "not-modified"
    assert responder.requested == [f"/3/tv/{ONE_PIECE}"]
    assert [sql for sql in episode_statements if sql.lower().lstrip().startswith(("update", "insert"))] == []


async def test_a_backoff_that_has_not_run_out_stops_the_fetch_before_a_request(db_session: AsyncSession) -> None:
    """Otherwise the backoff is written and never read: the cursor would earn a wait nobody honours."""
    cursors = PostgresResponseCache(db_session)
    await cursors.record_failure(ExternalSource.TMDB.value, "tmdb_tv", str(ONE_PIECE), "ProviderUnavailableError: x")
    responder = RoutingResponder(tv_routes(ONE_PIECE, "tv_37854", RECORDED_SEASONS))
    ingest = TmdbIngest(db_session, client_over(responder, db_session))

    outcome = await ingest.ingest_tv(ONE_PIECE)

    assert outcome.outcome == "throttled"
    assert outcome.skipped == 1
    assert responder.requested == []


async def test_a_second_series_keeps_its_own_seasons(db_session: AsyncSession) -> None:
    """`uq(title_id, season_number)` is per title: two series both have a season 2 and neither collides."""
    responder = RoutingResponder(tv_routes(INUYASHA, "tv_35610", (2,)))
    ingest = TmdbIngest(db_session, client_over(responder, db_session))

    await ingest.ingest_tv(INUYASHA)
    await db_session.flush()

    title = await _the_title(db_session, INUYASHA)
    numbers = list(
        await db_session.scalars(
            select(Episode.episode_number).where(Episode.title_id == title.id, Episode.season_number == 2)
        )
    )
    # InuYasha is numbered per season, so its season 2 opens at 1 - the same code, a different numbering.
    assert min(numbers) == 1


async def test_primary_poster_is_one_per_kind_per_title(db_session: AsyncSession) -> None:
    responder = RoutingResponder({f"/3/movie/{ATTACK_OF_THE_CLONES}": "movie_attack_of_the_clones"})
    ingest = TmdbIngest(db_session, client_over(responder, db_session))
    await ingest.ingest_movie(ATTACK_OF_THE_CLONES)
    await db_session.flush()
    title = await _the_title(db_session, ATTACK_OF_THE_CLONES, media_type=MediaType.MOVIE)

    first = _candidate(A_POSTER_PATH, language="en", vote=Decimal("5.0"))
    second = _candidate(ANOTHER_POSTER_PATH, language="en", vote=Decimal("9.0"))
    await ingest.ingest_artwork(title, [first], [])
    await db_session.flush()
    await ingest.ingest_artwork(title, [first, second], [])
    await db_session.flush()

    primaries = list(
        await db_session.scalars(
            select(Artwork.remote_path).where(
                Artwork.title_id == title.id, Artwork.kind == ArtworkKind.POSTER, Artwork.is_primary.is_(True)
            )
        )
    )
    assert primaries == [ANOTHER_POSTER_PATH]


async def test_a_provider_outage_leaves_the_projection_alone_instead_of_crashing_the_pass(
    db_session: AsyncSession,
) -> None:
    """A nightly job must report that nothing arrived, not raise out of the middle of a transaction."""
    responder = RoutingResponder({}, overrides={f"/3/movie/{ATTACK_OF_THE_CLONES}": httpx.Response(503)})
    ingest = TmdbIngest(db_session, client_over(responder, db_session))

    outcome = await ingest.ingest_movie(ATTACK_OF_THE_CLONES)
    await db_session.flush()

    assert outcome == IngestOutcome(outcome="not-modified")
    assert await db_session.scalar(select(func.count()).select_from(Title)) == 0
    # The client recorded the refusal against the cursor, which is what the backoff is read off next pass.
    failures = await db_session.scalar(
        select(SyncState.consecutive_failures).where(SyncState.resource_key == str(ATTACK_OF_THE_CLONES))
    )
    assert failures == 1


async def test_the_primary_posters_bytes_land_on_disk_and_only_a_path_lands_in_postgres(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    """The B11 round trip: composed URL, guarded fetch, uuid-named file, and a relative path in the row."""
    heroes = tmp_path / "heroes"
    images = MockResponder(httpx.Response(200, content=PNG))
    cache = ArtworkCache(Settings(_env_file=None, heroes_dir=heroes), transport=images.transport)
    responder = RoutingResponder(
        {f"/3/movie/{ATTACK_OF_THE_CLONES}": "movie_attack_of_the_clones"},
        overrides={"/3/configuration": _configuration_on(AN_IMAGE_HOST)},
    )
    ingest = TmdbIngest(db_session, client_over(responder, db_session), artwork=cache)

    await ingest.ingest_movie(ATTACK_OF_THE_CLONES)
    await db_session.flush()

    recorded = fixture_json(TMDB, "movie_attack_of_the_clones")
    primary = (
        await db_session.execute(
            select(Artwork.local_path, Artwork.remote_path).where(
                Artwork.kind == ArtworkKind.POSTER, Artwork.is_primary.is_(True)
            )
        )
    ).one()
    assert images.requested == [f"{AN_IMAGE_HOST}{TMDB_POSTER_SIZE}{recorded['poster_path']}"]
    assert primary.remote_path == recorded["poster_path"]
    assert primary.local_path is not None
    assert (heroes / primary.local_path).read_bytes() == PNG
    # The backdrop's bytes are never pulled: one image per title is what a card needs.
    backdrops = await db_session.scalar(
        select(func.count()).select_from(Artwork).where(Artwork.kind == ArtworkKind.BACKDROP)
    )
    assert backdrops == 1
    assert len(images.requested) == 1


async def test_a_season_past_the_six_month_caching_term_is_refetched_even_when_the_series_has_not_moved(
    db_session: AsyncSession,
) -> None:
    """TMDB's cap is per resource: a quiet series document does not renew a season's own term."""
    ingest, _ = one_piece_ingest(db_session)
    await ingest.ingest_tv(ONE_PIECE)
    await db_session.flush()

    later = utcnow() + timedelta(days=TMDB_CACHE_CEILING_DAYS + 1)
    responder = RoutingResponder(tv_routes(ONE_PIECE, "tv_37854", RECORDED_SEASONS))
    aged = TmdbIngest(db_session, client_over(responder, db_session), clock=lambda: later)

    await aged.ingest_tv(ONE_PIECE)

    fetched = {path for path in responder.requested if "/season/" in path}
    assert fetched == {f"/3/tv/{ONE_PIECE}/season/{number}" for number in RECORDED_SEASONS}


async def test_artwork_metadata_is_written_without_any_bytes_in_postgres(db_session: AsyncSession) -> None:
    responder = RoutingResponder({f"/3/movie/{ATTACK_OF_THE_CLONES}": "movie_attack_of_the_clones"})
    ingest = TmdbIngest(db_session, client_over(responder, db_session))

    await ingest.ingest_movie(ATTACK_OF_THE_CLONES)
    await db_session.flush()

    title = await _the_title(db_session, ATTACK_OF_THE_CLONES, media_type=MediaType.MOVIE)
    rows = list(
        await db_session.execute(
            select(Artwork.kind, Artwork.remote_path, Artwork.local_path).where(Artwork.title_id == title.id)
        )
    )
    recorded = fixture_json(TMDB, "movie_attack_of_the_clones")
    assert {kind for kind, _, _ in rows} == {ArtworkKind.POSTER, ArtworkKind.BACKDROP}
    assert {path for _, path, _ in rows} == {recorded["poster_path"], recorded["backdrop_path"]}
    # No cache was handed in, so nothing was downloaded and nothing claims a file on disk.
    assert {local for _, _, local in rows} == {None}
