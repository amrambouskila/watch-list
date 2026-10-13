from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tv_watchlist.data.enums import MediaImportOperationPhase, MediaImportSource, MediaImportStatus
from tv_watchlist.data.models import MediaImport, MediaImportOperation


async def _operation(session: AsyncSession, **overrides: object) -> MediaImportOperation:
    row = MediaImport(
        source=MediaImportSource.STAGING_FOLDER,
        source_path=str(uuid.uuid4()),
        original_name="f.mkv",
        size_bytes=3,
        status=MediaImportStatus.FOUND,
    )
    session.add(row)
    await session.flush()
    values: dict[str, object] = dict(
        media_import_id=row.id,
        phase=MediaImportOperationPhase.PREPARED,
        staging_root="/staging",
        media_root="/media",
        source_path=str(row.id),
        destination_path=str(row.id),
        temp_path=f"{row.id}.part",
        source_identity={"device": 1, "inode": 2, "size_bytes": 3, "mtime_ns": 4},
        source_sha256="a" * 64,
    )
    values.update(overrides)
    operation = MediaImportOperation(**values)
    session.add(operation)
    await session.flush()
    return operation


async def test_the_operation_survives_as_provenance(db_session: AsyncSession) -> None:
    operation = await _operation(db_session)
    assert operation.id is not None
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(delete(MediaImport).where(MediaImport.id == operation.media_import_id))


@pytest.mark.parametrize("field", ["source_sha256", "destination_sha256", "verified_sha256"])
@pytest.mark.parametrize("digest", ["a", "z" * 64, "A" * 64])
async def test_bad_digests_are_refused(db_session: AsyncSession, field: str, digest: str) -> None:
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await _operation(db_session, **{field: digest})


@pytest.mark.parametrize("field", ["source_path", "destination_path", "media_import_id"])
async def test_active_claims_are_unique(db_session: AsyncSession, field: str) -> None:
    first = await _operation(db_session)
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await _operation(db_session, **{field: getattr(first, field)})


@pytest.mark.parametrize(
    "phase",
    [
        MediaImportOperationPhase.COMPLETED,
        MediaImportOperationPhase.FAILED,
        MediaImportOperationPhase.DUPLICATE_SKIPPED,
    ],
)
async def test_terminal_history_releases_claims(db_session: AsyncSession, phase: MediaImportOperationPhase) -> None:
    first = await _operation(db_session, phase=phase)
    await _operation(
        db_session,
        source_path=first.source_path,
        destination_path=first.destination_path,
        media_import_id=first.media_import_id,
    )


@pytest.mark.parametrize(
    "fields",
    [
        {"rollback_status": MediaImportStatus.HASHED},
        {"phase": MediaImportOperationPhase.ROLLING_BACK},
        {"rollback_status": MediaImportStatus.FAILED},
    ],
)
async def test_rollback_intent_is_consistent(db_session: AsyncSession, fields: dict[str, object]) -> None:
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await _operation(db_session, **fields)
