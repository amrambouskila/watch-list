from __future__ import annotations

import asyncio
import threading
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, async_sessionmaker

from import_move_support import ImportMoveFixture
from tv_watchlist.data.enums import MediaImportOperationPhase, MediaImportStatus
from tv_watchlist.data.models import MediaImport, MediaImportOperation
from tv_watchlist.services import import_files, import_move
from tv_watchlist.services.import_files import ImportFiles
from tv_watchlist.services.import_move import move_one, move_pending, recover_pending
from tv_watchlist.services.import_source_lock import ImportSourceLock


@pytest.fixture
async def mover(engine: AsyncEngine, tmp_path: Path) -> AsyncIterator[ImportMoveFixture]:
    fixture = ImportMoveFixture(engine, tmp_path)
    try:
        yield fixture
    finally:
        await fixture.close()


async def test_verified_move_commits_then_removes_source(mover: ImportMoveFixture) -> None:
    original = await mover.seed()
    result = await move_one(mover.factory, mover.settings, original.id)
    assert result.status == MediaImportStatus.HASHED
    assert result.file_sha256 == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert result.file_path == "Movies/Film (2020)/Film (2020).mkv"
    assert (mover.media / result.file_path).read_bytes() == b"abc"
    assert not Path(original.source_path).exists()
    assert not list(mover.media.rglob("*.part"))
    assert (await mover.operation(original.id)).phase == MediaImportOperationPhase.COMPLETED
    assert await move_pending(mover.factory, mover.settings) == 0
    assert await recover_pending(mover.factory, mover.settings) == 0


async def test_identical_destination_keeps_source(mover: ImportMoveFixture) -> None:
    original = await mover.seed()
    destination = mover.media / "Movies/Film (2020)/Film (2020).mkv"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"abc")
    result = await move_one(mover.factory, mover.settings, original.id)
    assert result.status == MediaImportStatus.DUPLICATE_SKIPPED
    assert Path(original.source_path).read_bytes() == b"abc"
    assert destination.read_bytes() == b"abc"


async def test_different_destination_is_archived(mover: ImportMoveFixture) -> None:
    original = await mover.seed()
    destination = mover.media / "Movies/Film (2020)/Film (2020).mkv"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"older bytes")
    result = await move_one(mover.factory, mover.settings, original.id)
    operation = await mover.operation(original.id)
    assert result.status == MediaImportStatus.HASHED
    assert operation.superseded_path is not None
    assert (mover.media / operation.superseded_path).read_bytes() == b"older bytes"
    assert destination.read_bytes() == b"abc"


async def test_same_digest_elsewhere_preserves_staging(mover: ImportMoveFixture) -> None:
    first = await mover.seed("First")
    await move_one(mover.factory, mover.settings, first.id)
    second = await mover.seed("Second")
    result = await move_one(mover.factory, mover.settings, second.id)
    assert result.status == MediaImportStatus.DUPLICATE_SKIPPED
    assert Path(second.source_path).read_bytes() == b"abc"
    assert result.file_path is None
    assert not (mover.media / "Movies/Second (2020)/Second (2020).mkv").exists()


class SimulatedCrashError(RuntimeError):
    pass


@pytest.mark.parametrize("checkpoint", ["copy_temp", "install", "cleanup_source"])
async def test_restart_recovers_filesystem_ahead_of_journal(
    mover: ImportMoveFixture, monkeypatch: pytest.MonkeyPatch, checkpoint: str
) -> None:
    row = await mover.seed()
    original = getattr(ImportFiles, checkpoint)

    def crash_after_step(files: ImportFiles) -> object:
        original(files)
        raise SimulatedCrashError(checkpoint)

    with monkeypatch.context() as patch:
        patch.setattr(ImportFiles, checkpoint, crash_after_step)
        with pytest.raises(SimulatedCrashError):
            await move_one(mover.factory, mover.settings, row.id)
    assert await recover_pending(mover.factory, mover.settings) == 1
    assert (await mover.operation(row.id)).phase == MediaImportOperationPhase.COMPLETED
    assert not Path(row.source_path).exists()


async def test_restart_after_archiving_restores_forward_progress(
    mover: ImportMoveFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = await mover.seed()
    destination = mover.media / "Movies/Film (2020)/Film (2020).mkv"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"original")
    rename = import_files.rename_exclusive

    def crash_after_archive(source: Path, target: Path) -> None:
        rename(source, target)
        if "_superseded" in target.parts:
            raise SimulatedCrashError("archive moved")

    with monkeypatch.context() as patch:
        patch.setattr(import_files, "rename_exclusive", crash_after_archive)
        with pytest.raises(SimulatedCrashError):
            await move_one(mover.factory, mover.settings, row.id)
    assert Path(row.source_path).exists()
    assert not destination.exists()
    assert await recover_pending(mover.factory, mover.settings) == 1
    assert destination.read_bytes() == b"abc"
    operation = await mover.operation(row.id)
    assert (mover.media / operation.superseded_path).read_bytes() == b"original"


@pytest.mark.parametrize("after_commit", [False, True])
async def test_unknown_commit_outcome_preserves_source_until_recovery(
    mover: ImportMoveFixture, monkeypatch: pytest.MonkeyPatch, after_commit: bool
) -> None:
    row = await mover.seed()
    commit = AsyncSession.commit

    async def crash_committing(session: AsyncSession) -> None:
        is_final = any(
            isinstance(item, MediaImportOperation) and item.phase == MediaImportOperationPhase.COMMITTED
            for item in session.dirty
        )
        if is_final and not after_commit:
            raise SimulatedCrashError("commit response lost")
        await commit(session)
        if is_final:
            raise SimulatedCrashError("commit response lost")

    with monkeypatch.context() as patch:
        patch.setattr(AsyncSession, "commit", crash_committing)
        with pytest.raises(SimulatedCrashError):
            await move_one(mover.factory, mover.settings, row.id)
    assert Path(row.source_path).read_bytes() == b"abc"
    assert await recover_pending(mover.factory, mover.settings) == 1
    assert not Path(row.source_path).exists()


async def test_install_failure_compensates_and_preserves_source(
    mover: ImportMoveFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = await mover.seed()

    def refuse(source: Path, destination: Path) -> None:
        raise OSError("rename unavailable")

    monkeypatch.setattr(import_files, "rename_exclusive", refuse)
    result = await move_one(mover.factory, mover.settings, row.id)
    assert result.status == MediaImportStatus.FAILED
    assert "rename unavailable" in result.error
    assert Path(row.source_path).read_bytes() == b"abc"
    assert not list(mover.media.rglob("*.part"))
    assert (await mover.operation(row.id)).phase == MediaImportOperationPhase.FAILED


async def test_partial_copy_failure_removes_only_owned_temp(
    mover: ImportMoveFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = await mover.seed()

    def partial_then_refuse(source: object, destination: object, length: int) -> None:
        destination.write(b"a")
        raise OSError("disk full")

    monkeypatch.setattr(import_files.shutil, "copyfileobj", partial_then_refuse)
    result = await move_one(mover.factory, mover.settings, row.id)
    assert result.status == MediaImportStatus.FAILED
    assert not list(mover.media.rglob("*.part"))
    assert Path(row.source_path).read_bytes() == b"abc"


async def test_unknown_temp_after_create_crash_keeps_active_claim(
    mover: ImportMoveFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = await mover.seed()
    create = ImportFiles.create_temp

    def crash_after_create(files: ImportFiles) -> object:
        create(files)
        raise SimulatedCrashError("identity not yet committed")

    with monkeypatch.context() as patch:
        patch.setattr(ImportFiles, "create_temp", crash_after_create)
        with pytest.raises(SimulatedCrashError):
            await move_one(mover.factory, mover.settings, row.id)
    assert await recover_pending(mover.factory, mover.settings) == 0
    operation = await mover.operation(row.id)
    assert operation.phase == MediaImportOperationPhase.ROLLING_BACK
    assert "recovery required" in operation.error
    assert (mover.media / operation.temp_path).exists()
    assert Path(row.source_path).exists()


async def test_cleanup_failure_is_committed_not_failed(
    mover: ImportMoveFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = await mover.seed()

    def refuse(files: ImportFiles) -> None:
        raise PermissionError("source in use")

    with monkeypatch.context() as patch:
        patch.setattr(ImportFiles, "cleanup_source", refuse)
        result = await move_one(mover.factory, mover.settings, row.id)
    assert result.status == MediaImportStatus.HASHED
    assert (await mover.operation(row.id)).phase == MediaImportOperationPhase.COMMITTED
    assert Path(row.source_path).exists()
    assert await recover_pending(mover.factory, mover.settings) == 1


async def test_cancellation_drains_thread_and_keeps_both_locks(
    mover: ImportMoveFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = await mover.seed()
    entered, release = threading.Event(), threading.Event()
    copy = ImportFiles.copy_temp

    def blocked_copy(files: ImportFiles) -> object:
        entered.set()
        assert release.wait(5)
        return copy(files)

    monkeypatch.setattr(ImportFiles, "copy_temp", blocked_copy)
    task = asyncio.create_task(move_one(mover.factory, mover.settings, row.id))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        conflict = await move_one(mover.factory, mover.settings, row.id)
        assert conflict.status == MediaImportStatus.IDENTIFIED
        assert conflict.error is None
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert (await mover.operation(row.id)).phase == MediaImportOperationPhase.COMPLETED


async def test_source_lock_conflict_is_noop_not_failed(mover: ImportMoveFixture) -> None:
    row = await mover.seed()
    from tv_watchlist.models.import_file_identity import ImportFileIdentity

    path = Path(row.source_path)
    lock = ImportSourceLock(path, ImportFileIdentity.from_stat(path.stat()))
    assert lock.acquire()
    try:
        result = await move_one(mover.factory, mover.settings, row.id)
        assert result.status == MediaImportStatus.IDENTIFIED
        assert result.error is None
        assert await move_pending(mover.factory, mover.settings) == 0
    finally:
        lock.release()
    assert await move_pending(mover.factory, mover.settings) == 1


async def test_supersede_stamps_existing_provenance(mover: ImportMoveFixture) -> None:
    first = await mover.seed(content=b"old")
    await move_one(mover.factory, mover.settings, first.id)
    second = await mover.seed(content=b"new")
    await move_one(mover.factory, mover.settings, second.id)
    async with mover.factory() as session:
        old = await session.get(MediaImport, first.id)
        assert old.superseded_by_id == second.id
        assert old.superseded_at is not None
    operation = await mover.operation(second.id)
    assert (mover.media / operation.superseded_path).read_bytes() == b"old"


async def test_unknown_id_is_explicit(mover: ImportMoveFixture) -> None:
    with pytest.raises(LookupError):
        await move_one(mover.factory, mover.settings, uuid.uuid4())


@pytest.mark.parametrize("source_present", [True, False])
async def test_committed_recovery_requires_matching_provenance(
    mover: ImportMoveFixture, monkeypatch: pytest.MonkeyPatch, source_present: bool
) -> None:
    row = await mover.seed()

    def stop_cleanup(files: ImportFiles) -> None:
        raise PermissionError("retry cleanup")

    with monkeypatch.context() as patch:
        patch.setattr(ImportFiles, "cleanup_source", stop_cleanup)
        await move_one(mover.factory, mover.settings, row.id)
    if not source_present:
        Path(row.source_path).unlink()
    async with mover.factory() as session:
        changed = await session.get(MediaImport, row.id)
        changed.file_sha256 = "f" * 64
        await session.commit()
    assert await recover_pending(mover.factory, mover.settings) == 0
    operation = await mover.operation(row.id)
    assert operation.phase == MediaImportOperationPhase.COMMITTED
    assert "provenance" in operation.error.lower()
    assert Path(row.source_path).exists() == source_present


async def test_parent_swap_before_cleanup_is_refused(mover: ImportMoveFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    row = await mover.seed()
    commit = import_move._commit_import
    outside = mover.media.parent / "outside"
    outside.mkdir()
    replacement = outside / "Film (2020)"
    replacement.mkdir()
    (replacement / "Film (2020).mkv").write_bytes(b"external bytes")

    async def swap_parent_after_commit(
        session: AsyncSession, operation: MediaImportOperation, media_import: MediaImport, files: ImportFiles
    ) -> bool:
        committed = await commit(session, operation, media_import, files)
        (mover.media / "Movies").rename(mover.media / "original-movies")
        (mover.media / "Movies").symlink_to(outside, target_is_directory=True)
        return committed

    monkeypatch.setattr(import_move, "_commit_import", swap_parent_after_commit)
    result = await move_one(mover.factory, mover.settings, row.id)
    assert result.status == MediaImportStatus.HASHED
    assert (await mover.operation(row.id)).phase == MediaImportOperationPhase.COMMITTED
    assert Path(row.source_path).read_bytes() == b"abc"
    assert (replacement / "Film (2020).mkv").read_bytes() == b"external bytes"


async def test_batch_is_bounded_off_thread_and_writes_no_workbook(
    mover: ImportMoveFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tv_watchlist.services.catalog import Catalog

    for index in range(5):
        await mover.seed(f"Film {index}", f"unique {index}".encode())
    event_thread = threading.get_ident()
    barrier = threading.Barrier(2)
    gate = threading.Lock()
    running = peak = observed = 0
    copy = ImportFiles.copy_temp

    def tracked_copy(files: ImportFiles) -> object:
        nonlocal running, peak, observed
        assert threading.get_ident() != event_thread
        with gate:
            running += 1
            observed += 1
            at = observed
            peak = max(peak, running)
        try:
            if at <= 4:
                barrier.wait(timeout=5)
            return copy(files)
        finally:
            with gate:
                running -= 1

    def workbook_forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("Mover must not write a workbook")

    monkeypatch.setattr(ImportFiles, "copy_temp", tracked_copy)
    monkeypatch.setattr(Catalog, "_write", workbook_forbidden)
    assert await move_pending(mover.factory, mover.settings) == 5
    assert peak == mover.settings.import_concurrency


async def test_a_failed_import_does_not_rollback_a_healthy_batch_member(mover: ImportMoveFixture) -> None:
    bad = await mover.seed("Missing")
    Path(bad.source_path).unlink()
    healthy = await mover.seed("Healthy")
    assert await move_pending(mover.factory, mover.settings) == 1
    async with mover.factory() as session:
        assert (await session.get(MediaImport, bad.id)).status == MediaImportStatus.FAILED
        assert (await session.get(MediaImport, healthy.id)).status == MediaImportStatus.HASHED


@pytest.mark.parametrize("field", ["media_root", "import_staging_dir"])
async def test_missing_setup_is_unchanged_noop(mover: ImportMoveFixture, field: str) -> None:
    row = await mover.seed()
    settings = mover.settings.model_copy(update={field: None})
    result = await move_one(mover.factory, settings, row.id)
    assert result.status == MediaImportStatus.IDENTIFIED
    assert result.error is None
    assert await move_pending(mover.factory, settings) == 0


async def test_finished_import_is_unchanged_noop(mover: ImportMoveFixture) -> None:
    row = await mover.seed()
    first = await move_one(mover.factory, mover.settings, row.id)
    second = await move_one(mover.factory, mover.settings, row.id)
    assert second.status == first.status
    assert second.imported_at == first.imported_at


async def test_deleted_title_before_preparation_is_failed_without_mutation(mover: ImportMoveFixture) -> None:
    row = await mover.seed()
    async with mover.factory() as session:
        stored = await session.get(MediaImport, row.id)
        stored.title_id = None
        await session.commit()
    result = await move_one(mover.factory, mover.settings, row.id)
    assert result.status == MediaImportStatus.FAILED
    assert "target" in result.error
    assert Path(row.source_path).exists()


async def test_recovery_refuses_changed_roots_and_missing_precommit_source(
    mover: ImportMoveFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = await mover.seed()

    def pause(files: ImportFiles) -> object:
        raise SimulatedCrashError("prepared")

    with monkeypatch.context() as patch:
        patch.setattr(ImportFiles, "create_temp", pause)
        with pytest.raises(SimulatedCrashError):
            await move_one(mover.factory, mover.settings, row.id)
    changed = mover.settings.model_copy(update={"media_root": mover.media.parent / "another"})
    assert await recover_pending(mover.factory, changed) == 0
    assert "roots changed" in (await mover.operation(row.id)).error
    Path(row.source_path).unlink()
    assert await recover_pending(mover.factory, mover.settings) == 0
    assert "lost its staging source" in (await mover.operation(row.id)).error


async def test_racing_destination_claim_is_unchanged_noop(
    mover: ImportMoveFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second = await mover.seed(), await mover.seed(content=b"different")

    def pause(files: ImportFiles) -> object:
        raise SimulatedCrashError("prepared")

    with monkeypatch.context() as patch:
        patch.setattr(ImportFiles, "create_temp", pause)
        with pytest.raises(SimulatedCrashError):
            await move_one(mover.factory, mover.settings, first.id)
    conflict = await move_one(mover.factory, mover.settings, second.id)
    assert conflict.status == MediaImportStatus.IDENTIFIED
    assert conflict.error is None
    assert Path(first.source_path).exists() and Path(second.source_path).exists()


async def test_duplicate_conflict_restores_archive_and_provenance(mover: ImportMoveFixture) -> None:
    elsewhere = await mover.seed("Elsewhere", b"new")
    await move_one(mover.factory, mover.settings, elsewhere.id)
    old = await mover.seed(content=b"old")
    await move_one(mover.factory, mover.settings, old.id)
    new = await mover.seed(content=b"new")
    result = await move_one(mover.factory, mover.settings, new.id)
    assert result.status == MediaImportStatus.DUPLICATE_SKIPPED
    assert (mover.media / "Movies/Film (2020)/Film (2020).mkv").read_bytes() == b"old"
    assert Path(new.source_path).read_bytes() == b"new"
    async with mover.factory() as session:
        old_row = await session.get(MediaImport, old.id)
        assert old_row.superseded_at is None and old_row.superseded_by_id is None


async def test_rollback_restart_retains_original_duplicate_intent(
    mover: ImportMoveFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    elsewhere = await mover.seed("Elsewhere")
    await move_one(mover.factory, mover.settings, elsewhere.id)
    row = await mover.seed()

    def cannot_rollback(files: ImportFiles) -> None:
        raise PermissionError("temporarily unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(ImportFiles, "rollback", cannot_rollback)
        await move_one(mover.factory, mover.settings, row.id)
        assert await recover_pending(mover.factory, mover.settings) == 0
    assert (await mover.operation(row.id)).rollback_status == MediaImportStatus.DUPLICATE_SKIPPED
    assert await recover_pending(mover.factory, mover.settings) == 1
    assert (await mover.operation(row.id)).phase == MediaImportOperationPhase.DUPLICATE_SKIPPED


async def test_target_deleted_after_install_cannot_be_committed(
    mover: ImportMoveFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = await mover.seed()
    commit = import_move._commit_import

    async def remove_target(
        session: AsyncSession, operation: MediaImportOperation, media_import: MediaImport, files: ImportFiles
    ) -> bool:
        async with mover.factory() as other:
            stored = await other.get(MediaImport, row.id)
            stored.title_id = None
            await other.commit()
        return await commit(session, operation, media_import, files)

    monkeypatch.setattr(import_move, "_commit_import", remove_target)
    result = await move_one(mover.factory, mover.settings, row.id)
    assert result.status == MediaImportStatus.FAILED
    assert Path(row.source_path).read_bytes() == b"abc"


async def test_unbound_session_factory_is_refused(mover: ImportMoveFixture) -> None:
    with pytest.raises(TypeError, match="engine-bound"):
        await move_one(async_sessionmaker(), mover.settings, uuid.uuid4())


async def test_wrong_episode_target_is_failed(mover: ImportMoveFixture) -> None:
    from episode_join_support import a_show

    from tv_watchlist.data.models import Episode

    row = await mover.seed()
    async with mover.factory() as session:
        show = await a_show(session, "Other show", episodes=1)
        mover.titles.append(show.id)
        episode = await session.scalar(select(Episode).where(Episode.title_id == show.id))
        stored = await session.get(MediaImport, row.id)
        stored.episode_id = episode.id
        await session.commit()
    result = await move_one(mover.factory, mover.settings, row.id)
    assert result.status == MediaImportStatus.FAILED
    assert "does not belong" in result.error


async def test_non_claim_constraint_error_is_not_swallowed(
    mover: ImportMoveFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = await mover.seed()
    prepare = ImportFiles.prepare

    def invalid_intent(*args: object) -> MediaImportOperation:
        operation = prepare(*args)
        operation.source_sha256 = "invalid"
        return operation

    monkeypatch.setattr(ImportFiles, "prepare", invalid_intent)
    with pytest.raises(IntegrityError):
        await move_one(mover.factory, mover.settings, row.id)
    assert Path(row.source_path).read_bytes() == b"abc"
    assert not list(mover.media.rglob("*.part"))


async def test_non_duplicate_commit_error_does_not_abandon_healthy_batch(
    mover: ImportMoveFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad, healthy = await mover.seed("Bad", b"bad"), await mover.seed("Healthy", b"good")
    commit = AsyncSession.commit

    async def invalid_final_state(session: AsyncSession) -> None:
        for item in session.dirty:
            if isinstance(item, MediaImport) and item.id == bad.id and item.status == MediaImportStatus.HASHED:
                item.identified_by = None
        await commit(session)

    with monkeypatch.context() as patch:
        patch.setattr(AsyncSession, "commit", invalid_final_state)
        with pytest.raises(IntegrityError):
            await move_pending(mover.factory, mover.settings)
    assert Path(bad.source_path).read_bytes() == b"bad"
    assert (await mover.operation(healthy.id)).phase == MediaImportOperationPhase.COMPLETED
    assert await recover_pending(mover.factory, mover.settings) == 1


async def test_changed_status_before_commit_is_not_promoted(
    mover: ImportMoveFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = await mover.seed()
    commit = import_move._commit_import

    async def remove_identification(
        session: AsyncSession, operation: MediaImportOperation, media_import: MediaImport, files: ImportFiles
    ) -> bool:
        async with mover.factory() as other:
            stored = await other.get(MediaImport, row.id)
            stored.status = MediaImportStatus.FOUND
            await other.commit()
        return await commit(session, operation, media_import, files)

    monkeypatch.setattr(import_move, "_commit_import", remove_identification)
    result = await move_one(mover.factory, mover.settings, row.id)
    assert result.status == MediaImportStatus.FAILED
    assert "changed before commit" in result.error
    assert Path(row.source_path).exists()


async def test_repeated_cancellation_drains_a_failing_worker(
    mover: ImportMoveFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = await mover.seed()
    entered, release = threading.Event(), threading.Event()

    def stopped_copy(files: ImportFiles) -> object:
        entered.set()
        assert release.wait(5)
        raise SimulatedCrashError("worker failed after cancellation")

    monkeypatch.setattr(ImportFiles, "copy_temp", stopped_copy)
    task = asyncio.create_task(move_one(mover.factory, mover.settings, row.id))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert Path(row.source_path).read_bytes() == b"abc"


async def test_database_connection_loss_does_not_release_filesystem_ownership(
    mover: ImportMoveFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = await mover.seed()
    entered, release = threading.Event(), threading.Event()
    copy = ImportFiles.copy_temp
    scalar = AsyncConnection.scalar
    worker_pid: int | None = None

    async def capture_pid(connection: AsyncConnection, statement: object, *args: object, **kwargs: object) -> object:
        nonlocal worker_pid
        if "pg_try_advisory_lock" in str(statement) and worker_pid is None:
            worker_pid = await scalar(connection, text("SELECT pg_backend_pid()"))
        return await scalar(connection, statement, *args, **kwargs)

    def blocked_copy(files: ImportFiles) -> object:
        entered.set()
        assert release.wait(5)
        return copy(files)

    monkeypatch.setattr(AsyncConnection, "scalar", capture_pid)
    monkeypatch.setattr(ImportFiles, "copy_temp", blocked_copy)
    task = asyncio.create_task(move_one(mover.factory, mover.settings, row.id))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        assert worker_pid is not None
        async with mover.factory() as isolated:
            assert await isolated.scalar(text("SELECT pg_terminate_backend(:pid)"), {"pid": worker_pid})
            await isolated.commit()
        assert await recover_pending(mover.factory, mover.settings) == 0
        assert (await mover.operation(row.id)).phase == MediaImportOperationPhase.PREPARED
    finally:
        release.set()
        with pytest.raises(SQLAlchemyError):
            await task
    assert Path(row.source_path).read_bytes() == b"abc"
    assert await recover_pending(mover.factory, mover.settings) == 1


async def test_failed_unlock_invalidates_connection_instead_of_pooling_a_held_lock(
    mover: ImportMoveFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tv_watchlist.constants import IMPORT_LOCK_KEY_BITS

    row = await mover.seed()
    execute = AsyncConnection.execute

    async def failed_unlock(connection: AsyncConnection, statement: object, *args: object, **kwargs: object) -> object:
        if "pg_advisory_unlock" in str(statement):
            raise SQLAlchemyError("unlock transport failed")
        return await execute(connection, statement, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(AsyncConnection, "execute", failed_unlock)
        with pytest.raises(SQLAlchemyError, match="unlock transport"):
            await move_one(mover.factory, mover.settings, row.id)
    key = row.id.int & ((1 << IMPORT_LOCK_KEY_BITS) - 1)
    async with mover.factory() as session:
        assert await session.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": key})
        assert await session.scalar(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
    assert (await mover.operation(row.id)).phase == MediaImportOperationPhase.COMPLETED


async def test_recorded_tmdb_episode_62_lands_under_season_two(mover: ImportMoveFixture) -> None:
    from provider_fixtures import TMDB, fixture_json
    from tv_watchlist.data.enums import MediaType
    from tv_watchlist.data.models import Episode, Season, Title
    from tv_watchlist.models.tmdb.tmdb_season import TmdbSeason
    from tv_watchlist.models.tmdb.tmdb_tv import TmdbTv

    reference_title = TmdbTv.model_validate(fixture_json(TMDB, "tv_37854"))
    reference_episode = TmdbSeason.model_validate(fixture_json(TMDB, "tv_37854_season_2")).episodes[0]
    assert (reference_episode.season_number, reference_episode.episode_number) == (2, 62)
    row = await mover.seed()
    async with mover.factory() as session:
        title = Title(
            media_type=MediaType.TV,
            name=reference_title.name,
            original_name=reference_title.original_name,
            tmdb_id=reference_title.id,
            match_key="one piece",
        )
        session.add(title)
        await session.flush()
        mover.titles.append(title.id)
        season = Season(title_id=title.id, season_number=reference_episode.season_number)
        session.add(season)
        await session.flush()
        episode = Episode(
            title_id=title.id,
            season_id=season.id,
            season_number=reference_episode.season_number,
            episode_number=reference_episode.episode_number,
            tmdb_episode_id=reference_episode.id,
            name=reference_episode.name,
        )
        session.add(episode)
        await session.flush()
        stored = await session.get(MediaImport, row.id)
        stored.title_id, stored.episode_id = title.id, episode.id
        await session.commit()
    result = await move_one(mover.factory, mover.settings, row.id)
    assert result.status == MediaImportStatus.HASHED
    assert result.file_path.startswith("TV/ワンピース/Season 02/")
    assert "S02E62" in result.file_path
    assert (mover.media / result.file_path).read_bytes() == b"abc"


async def test_same_episode_id_changed_before_commit_is_refreshed_and_refused(
    mover: ImportMoveFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    from episode_join_support import a_show

    from tv_watchlist.data.models import Episode, Title

    row = await mover.seed()
    async with mover.factory() as session:
        show = await a_show(session, "Series", episodes=1)
        mover.titles.append(show.id)
        episode = await session.scalar(select(Episode).where(Episode.title_id == show.id))
        episode_id = episode.id
        stored = await session.get(MediaImport, row.id)
        stored.title_id, stored.episode_id = show.id, episode_id
        await session.commit()
    held: list[Episode] = []
    target, commit = import_move._target, import_move._commit_import

    async def hold_loaded_episode(session: AsyncSession, stored: MediaImport) -> tuple[Title, Episode | None]:
        title, episode = await target(session, stored)
        held.append(episode)
        return title, episode

    async def change_episode(
        session: AsyncSession, operation: MediaImportOperation, stored: MediaImport, files: ImportFiles
    ) -> bool:
        async with mover.factory() as other:
            episode = await other.get(Episode, episode_id)
            episode.episode_number, episode.name = 2, "Changed provider title"
            await other.commit()
        return await commit(session, operation, stored, files)

    monkeypatch.setattr(import_move, "_target", hold_loaded_episode)
    monkeypatch.setattr(import_move, "_commit_import", change_episode)
    result = await move_one(mover.factory, mover.settings, row.id)
    assert result.status == MediaImportStatus.FAILED
    assert "target changed before commit" in result.error
    assert Path(row.source_path).read_bytes() == b"abc"


@pytest.mark.parametrize("repeat_cancel", [False, True])
async def test_cancelled_batch_waits_for_every_active_worker(
    mover: ImportMoveFixture, monkeypatch: pytest.MonkeyPatch, repeat_cancel: bool
) -> None:
    from tv_watchlist.config import Settings

    first = await mover.seed("First", b"first")
    second = await mover.seed("Second", b"second")
    paths = (Path(first.source_path), Path(second.source_path))
    entered = (threading.Event(), threading.Event())
    release = (threading.Event(), threading.Event())
    first_finished, second_finished = asyncio.Event(), asyncio.Event()
    copy, owned = ImportFiles.copy_temp, import_move._owned

    def blocked_copy(files: ImportFiles) -> object:
        index = paths.index(files.source)
        entered[index].set()
        assert release[index].wait(10)
        return copy(files)

    async def observed_worker(
        factory: async_sessionmaker[AsyncSession], settings: Settings, identifier: uuid.UUID
    ) -> import_move.MoveResult:
        result = await owned(factory, settings, identifier)
        if identifier == first.id and result[1] == MediaImportOperationPhase.COMPLETED:
            first_finished.set()
        if identifier == second.id and result[1] == MediaImportOperationPhase.COMPLETED:
            second_finished.set()
        return result

    monkeypatch.setattr(ImportFiles, "copy_temp", blocked_copy)
    monkeypatch.setattr(import_move, "_owned", observed_worker)
    task = asyncio.create_task(move_pending(mover.factory, mover.settings))
    try:
        assert all(await asyncio.gather(*(asyncio.to_thread(event.wait, 5) for event in entered)))
        task.cancel()
        await asyncio.sleep(0)
        if repeat_cancel:
            task.cancel()
        release[0].set()
        await asyncio.wait_for(first_finished.wait(), timeout=5)
        completed, _ = await asyncio.wait({task}, timeout=0.05)
        assert not completed
        conflict = await move_one(mover.factory, mover.settings, second.id)
        assert conflict.status == MediaImportStatus.IDENTIFIED
    finally:
        for event in release:
            event.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.wait_for(second_finished.wait(), timeout=5)
    assert (await mover.operation(first.id)).phase == MediaImportOperationPhase.COMPLETED
    assert (await mover.operation(second.id)).phase == MediaImportOperationPhase.COMPLETED
