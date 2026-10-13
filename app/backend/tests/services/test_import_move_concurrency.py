from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from import_move_support import ImportMoveFixture
from tv_watchlist.config import Settings
from tv_watchlist.data.enums import MediaImportOperationPhase, MediaImportStatus
from tv_watchlist.data.models import Episode, MediaImport, MediaImportOperation, Title
from tv_watchlist.models.import_file_identity import ImportFileIdentity
from tv_watchlist.services import import_move
from tv_watchlist.services.import_files import ImportFiles
from tv_watchlist.services.import_move import move_one, recover_pending

_WAIT_SECONDS = 5


@pytest.fixture
async def mover(engine: AsyncEngine, tmp_path: Path) -> AsyncIterator[ImportMoveFixture]:
    fixture = ImportMoveFixture(engine, tmp_path)
    try:
        yield fixture
    finally:
        await fixture.close()


async def test_distinct_sources_racing_for_one_destination_have_one_durable_owner(
    mover: ImportMoveFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = [await mover.seed(content=content) for content in (b"first", b"second")]
    prepared = threading.Barrier(2)
    copying, release = threading.Event(), threading.Event()
    prepare, copy = ImportFiles.prepare, ImportFiles.copy_temp

    def simultaneous_prepare(
        cls: type[ImportFiles], settings: Settings, row: MediaImport, title: Title, episode: Episode | None
    ) -> MediaImportOperation:
        operation = prepare(settings, row, title, episode)
        prepared.wait(timeout=_WAIT_SECONDS)
        return operation

    def hold_claim(files: ImportFiles) -> ImportFileIdentity:
        copying.set()
        assert release.wait(_WAIT_SECONDS)
        return copy(files)

    monkeypatch.setattr(ImportFiles, "prepare", classmethod(simultaneous_prepare))
    monkeypatch.setattr(ImportFiles, "copy_temp", hold_claim)
    tasks = [asyncio.create_task(move_one(mover.factory, mover.settings, row.id)) for row in rows]
    try:
        done, pending = await asyncio.wait(tasks, timeout=_WAIT_SECONDS, return_when=asyncio.FIRST_COMPLETED)
        assert len(done) == len(pending) == 1
        refused = next(iter(done)).result()
        assert refused.status == MediaImportStatus.IDENTIFIED
        assert refused.error is None
        assert copying.is_set()
        assert all(Path(row.source_path).exists() for row in rows)
    finally:
        release.set()
        results = await asyncio.gather(*tasks)
    moved = next(row for row in results if row.status == MediaImportStatus.HASHED)
    retained = next(row for row in results if row.status == MediaImportStatus.IDENTIFIED)
    expected = b"first" if moved.id == rows[0].id else b"second"
    assert (mover.media / moved.file_path).read_bytes() == expected
    assert not Path(moved.source_path).exists()
    assert Path(retained.source_path).read_bytes() == (b"second" if expected == b"first" else b"first")
    assert (await mover.operation(moved.id)).phase == MediaImportOperationPhase.COMPLETED


async def test_same_digest_racing_at_distinct_destinations_keeps_one_live_copy_and_the_losing_source(
    mover: ImportMoveFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = [await mover.seed(name) for name in ("First", "Second")]
    ready = asyncio.Event()
    arrived = 0
    commit = import_move._commit_import

    async def simultaneous_commit(
        session: AsyncSession, operation: MediaImportOperation, row: MediaImport, files: ImportFiles
    ) -> bool:
        nonlocal arrived
        arrived += 1
        if arrived == len(rows):
            ready.set()
        await asyncio.wait_for(ready.wait(), timeout=_WAIT_SECONDS)
        return await commit(session, operation, row, files)

    monkeypatch.setattr(import_move, "_commit_import", simultaneous_commit)
    results = await asyncio.gather(*(move_one(mover.factory, mover.settings, row.id) for row in rows))
    assert {row.status for row in results} == {MediaImportStatus.HASHED, MediaImportStatus.DUPLICATE_SKIPPED}
    moved = next(row for row in results if row.status == MediaImportStatus.HASHED)
    retained = next(row for row in results if row.status == MediaImportStatus.DUPLICATE_SKIPPED)
    assert (mover.media / moved.file_path).read_bytes() == b"abc"
    assert moved.file_sha256 == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert not Path(moved.source_path).exists()
    assert Path(retained.source_path).read_bytes() == b"abc"
    operation = await mover.operation(retained.id)
    assert operation.phase == MediaImportOperationPhase.DUPLICATE_SKIPPED
    assert not (mover.media / operation.destination_path).exists()
    assert not (mover.media / operation.temp_path).exists()


async def test_source_changed_just_before_commit_is_never_removed_or_claimed_complete(
    mover: ImportMoveFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = await mover.seed()
    commit = import_move._commit_import

    async def change_source_before_commit(
        session: AsyncSession, operation: MediaImportOperation, stored: MediaImport, files: ImportFiles
    ) -> bool:
        files.source.write_bytes(b"new owner bytes")
        return await commit(session, operation, stored, files)

    monkeypatch.setattr(import_move, "_commit_import", change_source_before_commit)
    await move_one(mover.factory, mover.settings, row.id)
    operation = await mover.operation(row.id)
    assert operation.phase in (MediaImportOperationPhase.COMMITTED, MediaImportOperationPhase.ROLLING_BACK)
    assert "ownership" in operation.error
    assert Path(row.source_path).read_bytes() == b"new owner bytes"
    assert (mover.media / operation.destination_path).read_bytes() == b"abc"
    assert await recover_pending(mover.factory, mover.settings) == 0
    assert Path(row.source_path).read_bytes() == b"new owner bytes"


async def test_parent_swapped_just_before_commit_preserves_source_installed_bytes_and_outside_files(
    mover: ImportMoveFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = await mover.seed()
    commit = import_move._commit_import
    outside = mover.media.parent / "outside"
    outside.mkdir()
    (outside / "Film (2020).mkv").write_bytes(b"outside bytes")
    preserved = mover.media.parent / "preserved-installed"

    async def swap_parent_before_commit(
        session: AsyncSession, operation: MediaImportOperation, stored: MediaImport, files: ImportFiles
    ) -> bool:
        files.destination.parent.rename(preserved)
        files.destination.parent.symlink_to(outside, target_is_directory=True)
        return await commit(session, operation, stored, files)

    monkeypatch.setattr(import_move, "_commit_import", swap_parent_before_commit)
    result = await move_one(mover.factory, mover.settings, row.id)
    assert result.status == MediaImportStatus.IDENTIFIED
    operation = await mover.operation(row.id)
    assert operation.phase == MediaImportOperationPhase.ROLLING_BACK
    assert "recovery required" in operation.error
    assert Path(row.source_path).read_bytes() == b"abc"
    assert (preserved / "Film (2020).mkv").read_bytes() == b"abc"
    assert (outside / "Film (2020).mkv").read_bytes() == b"outside bytes"
    assert await recover_pending(mover.factory, mover.settings) == 0
