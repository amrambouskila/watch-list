"""Durable, source-retaining imports with caller-independent phase transactions."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable

from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from tv_watchlist.clock import utcnow
from tv_watchlist.config import Settings
from tv_watchlist.constants import IMPORT_LOCK_KEY_BITS
from tv_watchlist.data.enums import MediaImportOperationPhase as Phase
from tv_watchlist.data.enums import MediaImportStatus as Status
from tv_watchlist.data.enums import MediaType
from tv_watchlist.data.errors import ProjectionError
from tv_watchlist.data.models import Episode, MediaImport, MediaImportOperation, Title
from tv_watchlist.services.import_files import ImportFiles
from tv_watchlist.services.import_source_lock import ImportSourceLock

_TERMINAL = (Phase.COMPLETED, Phase.FAILED, Phase.DUPLICATE_SKIPPED)
_LIVE = (Status.MOVED, Status.HASHED, Status.REFRESHED)
type SessionFactory = async_sessionmaker[AsyncSession]
type MoveResult = tuple[MediaImport, Phase | None]


async def move_one(session_factory: SessionFactory, settings: Settings, import_id: uuid.UUID) -> MediaImport:
    """Return fresh detached provenance after an independently committed move or safe no-op."""
    row, _ = await _drained(lambda: _owned(session_factory, settings, import_id))
    return row


async def move_pending(session_factory: SessionFactory, settings: Settings) -> int:
    """Recover first, then move live identified rows using bounded independent workers."""
    recovered = await _pending_operations(session_factory, settings)
    async with session_factory() as session:
        active = select(MediaImportOperation.media_import_id).where(MediaImportOperation.phase.not_in(_TERMINAL))
        ids = list(
            await session.scalars(
                select(MediaImport.id).where(
                    MediaImport.status == Status.IDENTIFIED,
                    MediaImport.superseded_at.is_(None),
                    MediaImport.id.not_in(active),
                )
            )
        )
    moved = await _batch(session_factory, settings, ids)
    return sum(phase == Phase.COMPLETED for _, phase in (*recovered, *moved))


async def recover_pending(session_factory: SessionFactory, settings: Settings) -> int:
    """Reconcile nonterminal operations without guessing ownership of changed artifacts."""
    return sum(phase is not None for _, phase in await _pending_operations(session_factory, settings))


async def _pending_operations(session_factory: SessionFactory, settings: Settings) -> list[MoveResult]:
    async with session_factory() as session:
        ids = list(
            await session.scalars(
                select(MediaImportOperation.media_import_id)
                .where(MediaImportOperation.phase.not_in(_TERMINAL))
                .order_by(MediaImportOperation.created_at)
            )
        )
    return await _batch(session_factory, settings, ids)


async def _batch(session_factory: SessionFactory, settings: Settings, ids: list[uuid.UUID]) -> list[MoveResult]:
    pending = iter(ids)
    results: list[MoveResult] = []
    failures: list[Exception] = []

    async def run() -> None:
        for identifier in pending:
            try:
                results.append(await _drained(lambda: _owned(session_factory, settings, identifier)))
            except Exception as error:
                failures.append(error)

    async with asyncio.TaskGroup() as workers:
        for _ in range(min(len(ids), settings.import_concurrency)):
            workers.create_task(run())
    if failures:
        raise failures[0]
    return results


async def _drained(operation: Callable[[], Awaitable[MoveResult]]) -> MoveResult:
    task = asyncio.create_task(operation())
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except BaseException:
                break
        if not task.cancelled():
            task.exception()
        raise


async def _row(session: AsyncSession, identifier: uuid.UUID, *, lock: bool = False) -> MediaImport:
    query = select(MediaImport).where(MediaImport.id == identifier).options(selectinload(MediaImport.title))
    if lock:
        query = query.with_for_update()
    row = await session.scalar(query.execution_options(populate_existing=True))
    if row is None:
        raise LookupError("Media import does not exist")
    return row


async def _owned(session_factory: SessionFactory, settings: Settings, identifier: uuid.UUID) -> MoveResult:
    engine = session_factory.kw.get("bind")
    if not isinstance(engine, AsyncEngine):
        raise TypeError("Import workers require an engine-bound async session factory")
    key = identifier.int & ((1 << IMPORT_LOCK_KEY_BITS) - 1)
    async with engine.connect() as connection:
        acquired = await connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": key})
        await connection.commit()
        try:
            async with session_factory(bind=connection) as session:
                row = await _row(session, identifier, lock=bool(acquired))
                if not acquired:
                    return row, None
                operation = await session.scalar(
                    select(MediaImportOperation).where(
                        MediaImportOperation.media_import_id == identifier, MediaImportOperation.phase.not_in(_TERMINAL)
                    )
                )
                if operation is None:
                    if settings.media_root is None or settings.import_staging_dir is None:
                        return row, None
                    if row.status != Status.IDENTIFIED or row.superseded_at is not None:
                        return row, None
                    operation = await _prepare(session, settings, row)
                    if operation is None:
                        return await _row(session, identifier), None
                phase = await _source_owned(session, settings, operation, row)
                return await _row(session, identifier), phase
        finally:
            if acquired:
                try:
                    await connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
                    await connection.commit()
                except BaseException:
                    await connection.invalidate()
                    raise


async def _target(session: AsyncSession, row: MediaImport) -> tuple[Title, Episode | None]:
    title = None if row.title_id is None else await session.get(Title, row.title_id, populate_existing=True)
    episode = None if row.episode_id is None else await session.get(Episode, row.episode_id, populate_existing=True)
    if title is None or (title.media_type == MediaType.TV and episode is None):
        raise ValueError("Identified import no longer has a complete title/episode target")
    if episode is not None and (episode.title_id != title.id or title.media_type != MediaType.TV):
        raise ValueError("Import episode does not belong to its series")
    return title, episode


async def _source_owned(
    session: AsyncSession, settings: Settings, operation: MediaImportOperation, row: MediaImport
) -> Phase | None:
    ownership: ImportSourceLock | None = None
    try:
        files = await _files(settings, operation)
        if operation.phase == Phase.COMMITTED:
            await _require_committed(session, operation)
        if await asyncio.to_thread(files._identity, files.source) is None:
            if operation.phase != Phase.COMMITTED:
                raise OSError("Uncommitted operation lost its staging source; recovery needs owner review")
            await asyncio.to_thread(files.verify_installed)
            operation.phase, operation.error = Phase.COMPLETED, None
            await session.commit()
            return Phase.COMPLETED
        ownership = ImportSourceLock(files.source, files.source_identity)
        if not await asyncio.to_thread(ownership.acquire):
            return None
        return await _advance(session, settings, operation, row)
    except (OSError, ProjectionError, ValidationError) as error:
        operation.error = f"Recovery required: {error}"
        await session.commit()
        return None
    finally:
        if ownership is not None:
            await asyncio.to_thread(ownership.release)


async def _prepare(session: AsyncSession, settings: Settings, row: MediaImport) -> MediaImportOperation | None:
    try:
        title, episode = await _target(session, row)
        operation = await asyncio.to_thread(ImportFiles.prepare, settings, row, title, episode)
    except (OSError, ProjectionError, ValueError) as error:
        row.status, row.error = Status.FAILED, str(error)
        await session.commit()
        return None
    try:
        async with session.begin_nested():
            session.add(operation)
            await session.flush()
    except IntegrityError as error:
        if "ix_media_import_operation_active_" not in str(error.orig):
            raise
        return None
    await session.commit()
    return operation


async def _require_committed(session: AsyncSession, operation: MediaImportOperation) -> None:
    row = await _row(session, operation.media_import_id, lock=True)
    if (
        row.status not in (Status.HASHED, Status.REFRESHED)
        or row.file_path != operation.destination_path
        or row.file_sha256 != operation.verified_sha256
        or operation.verified_sha256 != operation.source_sha256
        or row.imported_at is None
        or row.superseded_at is not None
        or row.superseded_by_id is not None
    ):
        raise OSError("Committed operation disagrees with actual import provenance")


async def _files(settings: Settings, operation: MediaImportOperation) -> ImportFiles:
    return await asyncio.to_thread(ImportFiles, settings, operation)


async def _advance(
    session: AsyncSession, settings: Settings, operation: MediaImportOperation, row: MediaImport
) -> Phase | None:
    try:
        files = await _files(settings, operation)
        if operation.phase == Phase.ROLLING_BACK:
            return await _rollback(session, files, operation, row)
        if operation.phase == Phase.PREPARED:
            if await asyncio.to_thread(files.duplicate_at_destination):
                row.status, row.file_path, row.file_sha256 = (
                    Status.DUPLICATE_SKIPPED,
                    operation.destination_path,
                    operation.source_sha256,
                )
                row.error = None
                operation.phase = Phase.DUPLICATE_SKIPPED
                await session.commit()
                return Phase.DUPLICATE_SKIPPED
            if operation.temp_identity is None:
                identity = await asyncio.to_thread(files.create_temp)
                operation.temp_identity = identity.model_dump()
                await session.commit()
                files = await _files(settings, operation)
            identity = await asyncio.to_thread(files.copy_temp)
            operation.temp_identity = identity.model_dump()
            operation.phase = Phase.COPIED
            await session.commit()
            files = await _files(settings, operation)
        if operation.phase == Phase.COPIED:
            await asyncio.to_thread(files.install)
            operation.phase = Phase.INSTALLED
            await session.commit()
        if operation.phase == Phase.INSTALLED:
            operation.verified_sha256 = await asyncio.to_thread(files.verify_installed)
            committed = await _commit_import(session, operation, row, files)
            if not committed:
                operation = await session.get(MediaImportOperation, operation.id)
                row = await _row(session, row.id)
                return await _abort(
                    session,
                    settings,
                    operation,
                    row,
                    Status.DUPLICATE_SKIPPED,
                    "Identical bytes already have live provenance",
                )
        await _require_committed(session, operation)
        await asyncio.to_thread(files.cleanup_source)
        operation.phase, operation.error = Phase.COMPLETED, None
        await session.commit()
        return Phase.COMPLETED
    except (OSError, ProjectionError, ValidationError) as error:
        if operation.phase in (Phase.COMMITTED, Phase.ROLLING_BACK):
            operation.error = str(error)
            await session.commit()
            return None
        return await _abort(session, settings, operation, row, Status.FAILED, str(error))


async def _commit_import(
    session: AsyncSession, operation: MediaImportOperation, row: MediaImport, files: ImportFiles
) -> bool:
    identifier, operation_id = row.id, operation.id
    row = await _row(session, identifier, lock=True)
    if row.status != Status.IDENTIFIED or row.superseded_at is not None:
        raise OSError("Import provenance changed before commit")
    try:
        title, episode = await _target(session, row)
    except ValueError as error:
        raise OSError(str(error)) from error
    await asyncio.to_thread(files.verify_target, row, title, episode)
    old_rows = await session.scalars(
        select(MediaImport)
        .where(
            MediaImport.id != row.id,
            MediaImport.file_path == operation.destination_path,
            MediaImport.superseded_at.is_(None),
            MediaImport.status.in_(_LIVE),
        )
        .with_for_update()
    )
    stamp = utcnow()
    for old in old_rows:
        old.superseded_at, old.superseded_by_id = stamp, row.id
    await session.flush()
    row.status, row.file_path, row.file_sha256 = Status.HASHED, operation.destination_path, operation.verified_sha256
    row.imported_at, row.error = stamp, None
    operation.phase, operation.error = Phase.COMMITTED, None
    try:
        await session.commit()
        return True
    except IntegrityError as error:
        await session.rollback()
        if "ix_media_import_live_sha256" not in str(error.orig):
            raise
        await session.get(MediaImportOperation, operation_id, populate_existing=True)
        await _row(session, identifier)
        return False


async def _abort(
    session: AsyncSession,
    settings: Settings,
    operation: MediaImportOperation,
    row: MediaImport,
    status: Status,
    reason: str,
) -> Phase | None:
    operation.phase, operation.rollback_status, operation.error = Phase.ROLLING_BACK, status, reason
    await session.commit()
    try:
        return await _rollback(session, await _files(settings, operation), operation, row)
    except (OSError, ProjectionError, ValidationError) as error:
        operation.error = f"{reason}; recovery required: {error}"
        await session.commit()
        return None


async def _rollback(
    session: AsyncSession, files: ImportFiles, operation: MediaImportOperation, row: MediaImport
) -> Phase:
    await asyncio.to_thread(files.rollback)
    status = operation.rollback_status
    row.status, row.error = status, operation.error
    operation.phase = Phase.DUPLICATE_SKIPPED if status == Status.DUPLICATE_SKIPPED else Phase.FAILED
    operation.rollback_status = None
    await session.commit()
    return operation.phase
