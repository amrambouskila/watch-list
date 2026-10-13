"""Identify found media from the local projection, leaving every uncertain match for owner review."""

from __future__ import annotations

from datetime import date

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tv_watchlist.constants import IMPORT_TITLE_CANDIDATE_LIMIT, MEDIA_IMPORT_MIN_CONFIDENCE
from tv_watchlist.data.enums import MediaImportIdentifiedBy, MediaImportStatus, MediaType, OrderType
from tv_watchlist.data.models import Episode, MediaImport, Title
from tv_watchlist.models.filename_parse import FilenameParse
from tv_watchlist.models.identify_pass_result import IdentifyPassResult
from tv_watchlist.resolver.match_key import match_key
from tv_watchlist.services.episode_lookup import episode_for_sequence
from tv_watchlist.services.import_filename import parse_filename


async def identify(session: AsyncSession, media_import: MediaImport) -> MediaImport:
    """Identify one persisted live found row under a row lock; the caller owns commit or rollback."""
    await session.flush()
    await session.refresh(media_import, with_for_update=True)
    if (
        media_import.status is MediaImportStatus.FOUND
        and media_import.superseded_at is None
        and media_import.identified_by is None
    ):
        await _identify_found(session, media_import)
        await session.flush()
    return media_import


async def identify_pending(session: AsyncSession) -> IdentifyPassResult:
    """Claim live, undecided found rows without waiting for another caller's in-flight choices."""
    await session.flush()
    rows = (
        await session.scalars(
            select(MediaImport)
            .where(
                MediaImport.status == MediaImportStatus.FOUND,
                MediaImport.superseded_at.is_(None),
                MediaImport.identified_by.is_(None),
            )
            .order_by(MediaImport.found_at, MediaImport.id)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
    ).all()
    identified = 0
    for row in rows:
        await _identify_found(session, row)
        identified += row.status is MediaImportStatus.IDENTIFIED
    await session.flush()
    return IdentifyPassResult(identified=identified, unidentified=len(rows) - identified)


async def _identify_found(session: AsyncSession, row: MediaImport) -> None:
    parsed = parse_filename(row.original_name)
    row.title_id = row.episode_id = row.identified_by = None
    row.identification_confidence = parsed.confidence
    row.status = MediaImportStatus.UNIDENTIFIED
    row.error = "Filename has no confident single-item identity."
    if parsed.confidence < MEDIA_IMPORT_MIN_CONFIDENCE:
        return
    candidates = await _titles(session, parsed)
    if not candidates:
        row.error = "No matching title exists in the local projection."
        return
    title, similarity = candidates[0]
    row.identification_confidence = min(parsed.confidence, similarity)
    if len(candidates) > 1 and similarity == candidates[1][1]:
        row.error = "Ambiguous title: multiple projection titles have the same best score."
        return
    if row.identification_confidence < MEDIA_IMPORT_MIN_CONFIDENCE:
        row.error = "Title confidence is below the automatic identification threshold."
        return
    episode: Episode | None = None
    if title.media_type is MediaType.TV:
        if parsed.absolute_number is not None:
            episode = await episode_for_sequence(
                session, title.id, OrderType.ABSOLUTE.value, sequence=parsed.absolute_number
            )
            row.error = "No episode occupies that absolute sequence in the local projection."
        else:
            episode = await session.scalar(
                select(Episode).where(
                    Episode.title_id == title.id,
                    Episode.season_number == parsed.season_number,
                    Episode.episode_number == parsed.episode_number,
                )
            )
            row.error = "No episode has that season/episode pair in the local projection."
        if episode is None:
            return
    row.title_id = title.id
    row.episode_id = None if episode is None else episode.id
    row.identified_by = MediaImportIdentifiedBy.FILENAME
    row.status = MediaImportStatus.IDENTIFIED
    row.error = None


async def _titles(session: AsyncSession, parsed: FilenameParse) -> list[tuple[Title, float]]:
    episodic = parsed.season_number is not None or parsed.absolute_number is not None
    predicates: list[ColumnElement[bool]] = [Title.media_type == (MediaType.TV if episodic else MediaType.MOVIE)]
    if parsed.year is not None:
        predicates.extend(
            (Title.first_air_date >= date(parsed.year, 1, 1), Title.first_air_date < date(parsed.year + 1, 1, 1))
        )
    exact = (
        await session.scalars(
            select(Title)
            .where(*predicates, Title.match_key == match_key(parsed.series_token, year=parsed.year))
            .limit(IMPORT_TITLE_CANDIDATE_LIMIT)
            .with_for_update(read=True)
        )
    ).all()
    if exact:
        return [(title, 1.0) for title in exact]
    similarity = func.similarity(Title.name, parsed.series_token)
    candidates = await session.execute(
        select(Title, similarity)
        .where(*predicates, Title.name.bool_op("%")(parsed.series_token))
        .order_by(similarity.desc())
        .limit(IMPORT_TITLE_CANDIDATE_LIMIT)
        .with_for_update(read=True)
    )
    return [(title, score) for title, score in candidates]
