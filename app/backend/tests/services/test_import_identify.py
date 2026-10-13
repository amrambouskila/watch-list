"""Projection-only import identification against real PostgreSQL."""

from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path
from typing import NoReturn

import pytest
from episode_join_support import a_film, a_show, one_piece_with_its_orderings
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tv_watchlist.clients.tmdb_client import TmdbClient
from tv_watchlist.clock import utcnow
from tv_watchlist.constants import MEDIA_IMPORT_MIN_BYTES
from tv_watchlist.data.enums import ExternalSource, MediaImportIdentifiedBy, MediaImportSource, MediaImportStatus
from tv_watchlist.data.models import Episode, EpisodeOrder, MediaImport, Title
from tv_watchlist.resolver.match_key import match_key
from tv_watchlist.services.catalog import Catalog
from tv_watchlist.services.import_identify import identify, identify_pending
from tv_watchlist.services.import_naming import plan_destination


async def _found(session: AsyncSession, name: str) -> MediaImport:
    row = MediaImport(
        original_name=name,
        source_path=f"/staging/{name}",
        size_bytes=MEDIA_IMPORT_MIN_BYTES,
        source=MediaImportSource.STAGING_FOLDER,
        status=MediaImportStatus.FOUND,
    )
    session.add(row)
    await session.flush()
    return row


async def _dated(session: AsyncSession, title: Title, year: int) -> Title:
    title.first_air_date = date(year, 1, 1)
    title.match_key = match_key(title.name, year=year)
    await session.flush()
    return title


async def test_an_exact_key_identifies_a_movie_without_an_episode(db_session: AsyncSession) -> None:
    title = await _dated(db_session, await a_film(db_session, "The Matrix"), 1999)
    row = await _found(db_session, "The.Matrix.(1999).mkv")

    assert await identify(db_session, row) is row

    assert row.title_id == title.id
    assert row.episode_id is None
    assert row.status is MediaImportStatus.IDENTIFIED
    assert row.identified_by is MediaImportIdentifiedBy.FILENAME
    assert row.identification_confidence == pytest.approx(0.95)
    assert row.error is None


async def test_an_exact_season_episode_pair_matches(db_session: AsyncSession) -> None:
    title = await a_show(db_session, "A Show", episodes=2)
    title.match_key = match_key(title.name)
    await db_session.flush()
    row = await _found(db_session, "A.Show.S01E02.mkv")

    await identify(db_session, row)

    episode = await db_session.get(Episode, row.episode_id)
    assert episode is not None
    assert (episode.title_id, episode.season_number, episode.episode_number) == (title.id, 1, 2)


async def test_a_missing_filename_year_matches_the_dated_series_by_trigram(db_session: AsyncSession) -> None:
    title = await _dated(db_session, await a_show(db_session, "One Piece", episodes=2), 1999)
    row = await _found(db_session, "One.Piece.S01E02.mkv")
    await identify(db_session, row)
    assert row.title_id == title.id
    assert row.status is MediaImportStatus.IDENTIFIED


async def test_a_fuzzy_title_uses_the_lower_of_parse_and_similarity_confidences(db_session: AsyncSession) -> None:
    title = await _dated(db_session, await a_film(db_session, "The Fellowship of the Ring"), 2001)
    row = await _found(db_session, "The.Fellowship.of.the.Rings.(2001).mkv")
    similarity = await db_session.scalar(select(func.similarity(title.name, "The Fellowship of the Rings")))
    assert similarity is not None and similarity > 0.8

    await identify(db_session, row)

    assert row.title_id == title.id
    assert row.identification_confidence == pytest.approx(min(0.95, similarity))


@pytest.mark.parametrize("exact", [True, False], ids=["exact-key-tie", "trigram-tie"])
async def test_tied_titles_are_unidentified(db_session: AsyncSession, exact: bool) -> None:
    for _ in range(2):
        await _dated(db_session, await a_film(db_session, "The Fellowship of the Ring"), 2001)
    name = "The Fellowship of the Ring" if exact else "The Fellowship of the Rings"
    row = await _found(db_session, f"{name} (2001).mkv")
    await identify(db_session, row)
    assert row.status is MediaImportStatus.UNIDENTIFIED
    assert row.title_id is row.episode_id is row.identified_by is None
    assert row.error is not None and "ambiguous" in row.error.lower()


@pytest.mark.parametrize(
    ("name", "reason"),
    [
        ("Unknown.mkv", "filename"),
        ("Unrelated (1999).mkv", "title"),
        ("The Matrixx (1999).mkv", "confidence"),
        ("東京 (1999).mkv", "filename"),
    ],
)
async def test_unrecognised_names_and_low_scores_are_unidentified(
    db_session: AsyncSession,
    name: str,
    reason: str,
) -> None:
    await _dated(db_session, await a_film(db_session, "The Matrix"), 1999)
    row = await _found(db_session, name)
    await identify(db_session, row)
    assert row.status is MediaImportStatus.UNIDENTIFIED
    assert row.title_id is row.episode_id is row.identified_by is None
    assert row.error is not None and reason in row.error.lower()


async def test_supplied_year_and_media_type_constrain_fallback(db_session: AsyncSession) -> None:
    await _dated(db_session, await a_film(db_session, "Superman"), 2025)
    await _dated(db_session, await a_show(db_session, "Superman", episodes=1), 1978)
    row = await _found(db_session, "Superman (1978).mkv")
    await identify(db_session, row)
    assert row.status is MediaImportStatus.UNIDENTIFIED
    assert row.title_id is None


async def test_missing_episode_never_identifies_a_series_only(db_session: AsyncSession) -> None:
    await a_show(db_session, "Series", episodes=1)
    row = await _found(db_session, "Series.S01E02.mkv")
    await identify(db_session, row)
    assert row.status is MediaImportStatus.UNIDENTIFIED
    assert row.title_id is row.episode_id is None
    assert row.error is not None and "episode" in row.error.lower()


async def test_absolute_order_never_falls_back_to_aired(db_session: AsyncSession) -> None:
    await a_show(db_session, "Series", episodes=1)
    row = await _found(db_session, "Series - 1.mkv")
    await identify(db_session, row)
    assert row.status is MediaImportStatus.UNIDENTIFIED
    assert row.title_id is row.episode_id is None
    assert row.error is not None and "absolute" in row.error.lower()


async def test_seeded_absolute_1085_uses_the_projection_pair_in_the_destination(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    """A seeded projection reference, not a claim about a recorded provider response for episode 1085."""
    title = await a_show(db_session, "One Piece", episodes=1, season_number=22)
    episode = (await db_session.scalars(select(Episode).where(Episode.title_id == title.id))).one()
    episode.episode_number = 1085
    episode.name = "Seeded episode reference"
    db_session.add(
        EpisodeOrder(
            title_id=title.id,
            episode_id=episode.id,
            order_type="absolute",
            label="",
            sequence=1085,
            source=ExternalSource.TVDB,
        )
    )
    await db_session.flush()
    row = await _found(db_session, "[Group] One Piece - 1085v2 (1080p).mkv")

    await identify(db_session, row)

    assert row.episode_id == episode.id
    destination = plan_destination(tmp_path, title, episode, ".mkv")
    assert str(destination.relative_path) == "TV/One Piece/Season 22/One Piece S22E1085 - Seeded episode reference.mkv"


async def test_recorded_absolute_62_keeps_tmdb_s02e62(db_session: AsyncSession, tmp_path: Path) -> None:
    title = await one_piece_with_its_orderings(db_session)
    row = await _found(db_session, "One Piece - 62.mkv")
    await identify(db_session, row)
    episode = await db_session.get(Episode, row.episode_id)
    assert episode is not None
    assert (episode.season_number, episode.episode_number) == (2, 62)
    assert " S02E62" in str(plan_destination(tmp_path, title, episode, ".mkv").relative_path)


async def test_identify_pending_reports_counts_only_for_live_found_rows(db_session: AsyncSession) -> None:
    title = await _dated(db_session, await a_film(db_session, "Film"), 1999)
    good = await _found(db_session, "Film (1999).mkv")
    bad = await _found(db_session, "nonsense.mkv")
    owner = await _found(db_session, "owner picked.mkv")
    owner.title_id, owner.identified_by = title.id, MediaImportIdentifiedBy.OWNER_PICK
    retired = await _found(db_session, "retired.mkv")
    retired.superseded_at, retired.superseded_by_id = utcnow(), good.id
    previous = await _found(db_session, "already stopped.mkv")
    previous.status, previous.error = MediaImportStatus.UNIDENTIFIED, "Owner review needed"
    await db_session.flush()

    result = await identify_pending(db_session)

    assert result.identified == result.unidentified == 1
    assert good.status is MediaImportStatus.IDENTIFIED
    assert bad.status is MediaImportStatus.UNIDENTIFIED
    assert owner.identified_by is MediaImportIdentifiedBy.OWNER_PICK
    assert retired.status is MediaImportStatus.FOUND
    assert previous.error == "Owner review needed"
    assert (await identify_pending(db_session)).model_dump() == {"identified": 0, "unidentified": 0}


async def test_identify_does_not_replace_an_owner_choice(db_session: AsyncSession) -> None:
    row = await _found(db_session, "nonsense.mkv")
    row.status, row.identified_by = MediaImportStatus.IDENTIFIED, MediaImportIdentifiedBy.OWNER_PICK
    await db_session.flush()
    await identify(db_session, row)
    assert row.status is MediaImportStatus.IDENTIFIED
    assert row.identified_by is MediaImportIdentifiedBy.OWNER_PICK


async def test_no_provider_is_constructed_and_no_workbook_is_written(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    title = await _dated(db_session, await a_film(db_session, "Film"), 1999)
    row = await _found(db_session, "Film (1999).mkv")

    def forbidden(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError("Identification cannot construct a provider or mutate a workbook")

    monkeypatch.setattr(TmdbClient, "__init__", forbidden)
    monkeypatch.setattr(Catalog, "_write", forbidden)

    assert (await identify_pending(db_session)).identified == 1
    assert row.title_id == title.id


async def test_a_refusal_clears_stale_unconfirmed_identity_hints(db_session: AsyncSession) -> None:
    title = await a_show(db_session, "Series", episodes=1)
    episode = (await db_session.scalars(select(Episode).where(Episode.title_id == title.id))).one()
    row = await _found(db_session, "unrecognised.mkv")
    row.title_id, row.episode_id = title.id, episode.id
    await db_session.flush()
    await identify(db_session, row)
    assert row.title_id is row.episode_id is row.identified_by is None
    assert row.status is MediaImportStatus.UNIDENTIFIED


async def test_empty_normalised_name_cannot_match_a_year_only_key(db_session: AsyncSession) -> None:
    await _dated(db_session, await a_film(db_session, "東京"), 1999)
    row = await _found(db_session, "東京 (1999).mkv")
    await identify(db_session, row)
    assert row.status is MediaImportStatus.UNIDENTIFIED
    assert row.title_id is None


async def test_a_removed_projection_title_never_becomes_an_identified_row(db_session: AsyncSession) -> None:
    title = await _dated(db_session, await a_film(db_session, "Film"), 1999)
    row = await _found(db_session, "Film (1999).mkv")
    await db_session.delete(title)
    await db_session.flush()
    await identify(db_session, row)
    assert row.status is MediaImportStatus.UNIDENTIFIED
    assert row.title_id is row.identified_by is None


async def test_raw_fuzzy_scores_are_compared_before_the_parse_confidence_cap(db_session: AsyncSession) -> None:
    name = "The Extraordinary Adventures of a Travelling Astronomer Across the Known Universe"
    title = await _dated(db_session, await a_show(db_session, name, episodes=1), 2000)
    other = await _dated(db_session, await a_show(db_session, name + "s", episodes=1), 2001)
    score = await db_session.scalar(select(func.similarity(other.name, name)))
    assert score is not None and 0.95 < score < 1
    row = await _found(db_session, f"{name}.S01E01.mkv")
    await identify(db_session, row)
    assert row.title_id == title.id
    assert row.identification_confidence == pytest.approx(0.95)


async def test_the_minimum_confidence_is_inclusive(db_session: AsyncSession) -> None:
    title = await _dated(db_session, await a_film(db_session, "abcdefghijkl"), 1999)
    row = await _found(db_session, "abcdefghijklm (1999).mkv")
    assert await db_session.scalar(select(func.similarity(title.name, "abcdefghijklm"))) == pytest.approx(0.8)
    await identify(db_session, row)
    assert row.status is MediaImportStatus.IDENTIFIED
    assert row.identification_confidence == pytest.approx(0.8)


@pytest.mark.parametrize("commit", [True, False], ids=["caller-commit", "caller-rollback"])
async def test_pending_rows_stay_claimed_until_the_caller_ends_its_transaction(
    engine: AsyncEngine,
    commit: bool,
) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as seed:
        row = await _found(seed, "unrecognised concurrency reference.mkv")
        await seed.commit()
        row_id = row.id
    try:
        async with AsyncSession(engine, expire_on_commit=False) as first, AsyncSession(engine) as second:
            assert (await identify_pending(first)).unidentified == 1
            assert (await identify_pending(second)).model_dump() == {"identified": 0, "unidentified": 0}
            await second.rollback()
            if commit:
                await first.commit()
            else:
                await first.rollback()
            assert (await identify_pending(second)).unidentified == int(not commit)
    finally:
        async with AsyncSession(engine) as cleanup:
            await cleanup.execute(delete(MediaImport).where(MediaImport.id == row_id))
            await cleanup.commit()


async def test_direct_identify_rechecks_an_owner_choice_after_waiting_for_its_row_lock(engine: AsyncEngine) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as seed:
        row = await _found(seed, "unrecognised owner race reference.mkv")
        await seed.commit()
        row_id = row.id
    try:
        async with AsyncSession(engine, expire_on_commit=False) as owner, AsyncSession(engine) as automatic:
            stale = await automatic.get(MediaImport, row_id)
            chosen = await owner.get(MediaImport, row_id, with_for_update=True)
            assert stale is not None and chosen is not None
            chosen.identified_by, chosen.status = MediaImportIdentifiedBy.OWNER_PICK, MediaImportStatus.IDENTIFIED
            await owner.flush()
            waiting = asyncio.create_task(identify(automatic, stale))
            try:
                with pytest.raises(TimeoutError):
                    await asyncio.wait_for(asyncio.shield(waiting), timeout=0.1)
                await owner.commit()
                result = await asyncio.wait_for(waiting, timeout=2)
                assert result.identified_by is MediaImportIdentifiedBy.OWNER_PICK
                assert result.status is MediaImportStatus.IDENTIFIED
            finally:
                if not waiting.done():
                    waiting.cancel()
                    await asyncio.gather(waiting, return_exceptions=True)
    finally:
        async with AsyncSession(engine) as cleanup:
            await cleanup.execute(delete(MediaImport).where(MediaImport.id == row_id))
            await cleanup.commit()
