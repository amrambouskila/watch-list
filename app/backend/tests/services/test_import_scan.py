"""Discovery uses real files and PostgreSQL; it never moves, hashes or opens a workbook."""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Final

import httpx
import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from import_scan_support import media_file
from provider_fixtures import QBITTORRENT, fixture_response, fixture_rows, qbittorrent_client_for
from statement_support import counted_statements
from tv_watchlist.clock import utcnow
from tv_watchlist.config import Settings
from tv_watchlist.constants import MEDIA_IMPORT_EXTENSIONS, MEDIA_IMPORT_LOOKUP_BATCH_SIZE, MEDIA_IMPORT_MIN_BYTES
from tv_watchlist.data.enums import MediaImportIdentifiedBy, MediaImportSource, MediaImportStatus
from tv_watchlist.data.models.media_import import MediaImport
from tv_watchlist.services.import_scan import scan

LOGGER_NAME: Final[str] = "tv_watchlist.services.import_scan"
MULTI_FILE_FIXTURE: Final[str] = "torrents_files_multi"
TORRENTS_FIXTURE: Final[str] = "torrents_info_completed"
LOCK_WAIT_SECONDS: Final[float] = 0.1
LOCK_RELEASE_SECONDS: Final[float] = 2.0
LARGE_FILE_BYTES: Final[int] = 3 * 1024**3


def _torrent(root: Path, index: int = 0) -> dict[str, object]:
    return fixture_rows(QBITTORRENT, TORRENTS_FIXTURE)[index] | {"save_path": str(root)}


async def test_a_media_file_in_staging_becomes_a_found_row(db_session: AsyncSession, tmp_path: Path) -> None:
    source = media_file(tmp_path / "film.mkv")
    settings = Settings(_env_file=None, import_staging_dir=tmp_path)

    result = await scan(db_session, settings, qbittorrent=None)

    row = (await db_session.scalars(select(MediaImport))).one()
    assert result.found == result.candidates_seen == 1
    assert row.source_path == str(source.resolve())
    assert row.original_name == source.name
    assert row.size_bytes == MEDIA_IMPORT_MIN_BYTES
    assert row.source is MediaImportSource.STAGING_FOLDER
    assert row.status is MediaImportStatus.FOUND
    assert row.title_id is row.file_path is row.file_sha256 is None
    assert source.stat().st_size == MEDIA_IMPORT_MIN_BYTES


async def test_a_nested_torrent_folder_is_walked(db_session: AsyncSession, tmp_path: Path) -> None:
    source = media_file(tmp_path / "Series" / "Season 01" / "episode.mkv")

    result = await scan(db_session, Settings(_env_file=None, import_staging_dir=tmp_path), qbittorrent=None)

    assert result.found == 1
    assert (await db_session.scalars(select(MediaImport.source_path))).one() == str(source.resolve())


@pytest.mark.parametrize("suffix", sorted(MEDIA_IMPORT_EXTENSIONS), ids=lambda suffix: suffix)
async def test_every_allowlisted_extension_is_case_insensitive(
    db_session: AsyncSession, tmp_path: Path, suffix: str
) -> None:
    media_file(tmp_path / f"film{suffix.upper()}")

    result = await scan(db_session, Settings(_env_file=None, import_staging_dir=tmp_path), qbittorrent=None)

    assert result.found == 1


async def test_small_and_wrong_extension_files_are_counted_once(db_session: AsyncSession, tmp_path: Path) -> None:
    media_file(tmp_path / "sample.mkv", MEDIA_IMPORT_MIN_BYTES - 1)
    media_file(tmp_path / "program.exe", LARGE_FILE_BYTES)
    media_file(tmp_path / "zero.mkv", 0)
    media_file(tmp_path / "full.mkv", LARGE_FILE_BYTES)

    result = await scan(db_session, Settings(_env_file=None, import_staging_dir=tmp_path), qbittorrent=None)

    assert (result.candidates_seen, result.found, result.too_small, result.wrong_extension) == (4, 1, 2, 1)
    assert (await db_session.scalars(select(MediaImport.size_bytes))).one() == LARGE_FILE_BYTES


@pytest.mark.parametrize("directory", [False, True], ids=["file-link", "directory-link"])
async def test_a_symlink_out_of_staging_is_refused_and_counted(
    db_session: AsyncSession, tmp_path: Path, directory: bool
) -> None:
    root = tmp_path / "staging"
    root.mkdir()
    outside = media_file(tmp_path / "outside" / "film.mkv")
    (root / "escape.mkv").symlink_to(outside.parent if directory else outside, target_is_directory=directory)

    result = await scan(db_session, Settings(_env_file=None, import_staging_dir=root), qbittorrent=None)

    assert result.path_refused == 1
    assert result.candidates_seen == result.found == 0
    assert (await db_session.scalars(select(MediaImport))).all() == []
    assert outside.stat().st_size == MEDIA_IMPORT_MIN_BYTES


async def test_internal_file_links_share_one_canonical_path(db_session: AsyncSession, tmp_path: Path) -> None:
    source = media_file(tmp_path / "actual.mkv")
    (tmp_path / "alias.mkv").symlink_to(source)
    (tmp_path / "directory-alias").symlink_to(tmp_path, target_is_directory=True)

    result = await scan(db_session, Settings(_env_file=None, import_staging_dir=tmp_path), qbittorrent=None)

    assert result.found == result.candidates_seen == 1
    assert result.path_refused == 1  # A link to the root itself is not a file under that root.
    assert (await db_session.scalars(select(MediaImport.source_path))).one() == str(source.resolve())


async def test_a_second_scan_writes_nothing(db_session: AsyncSession, engine: AsyncEngine, tmp_path: Path) -> None:
    media_file(tmp_path / "film.mkv")
    settings = Settings(_env_file=None, import_staging_dir=tmp_path)
    first = await scan(db_session, settings, qbittorrent=None)

    with counted_statements(engine, "media_import") as statements:
        second = await scan(db_session, settings, qbittorrent=None)

    assert first.found == second.already_known == 1
    assert second.found == 0
    assert all(statement.lstrip().upper().startswith("SELECT") for statement in statements)
    assert (await db_session.scalar(select(func.count()).select_from(MediaImport))) == 1


async def test_large_scans_batch_existing_path_queries(
    db_session: AsyncSession, engine: AsyncEngine, tmp_path: Path
) -> None:
    count = MEDIA_IMPORT_LOOKUP_BATCH_SIZE + 1
    for number in range(count):
        media_file(tmp_path / f"film-{number}.mkv")
    settings = Settings(_env_file=None, import_staging_dir=tmp_path)
    assert (await scan(db_session, settings, qbittorrent=None)).found == count

    with counted_statements(engine, "media_import") as statements:
        result = await scan(db_session, settings, qbittorrent=None)

    assert result.already_known == count
    assert result.found == 0
    assert len(statements) == 2
    assert all(statement.lstrip().upper().startswith("SELECT") for statement in statements)


@pytest.mark.parametrize("status", list(MediaImportStatus), ids=lambda status: status.value)
async def test_live_nonfailed_history_prevents_a_new_row(
    db_session: AsyncSession, tmp_path: Path, status: MediaImportStatus
) -> None:
    source = media_file(tmp_path / "film.mkv")
    db_session.add(
        MediaImport(
            source=MediaImportSource.STAGING_FOLDER,
            source_path=str(source.resolve()),
            original_name=source.name,
            size_bytes=MEDIA_IMPORT_MIN_BYTES,
            status=status,
            identified_by=MediaImportIdentifiedBy.OWNER_PICK,
            file_path="Movies/film.mkv",
            file_sha256="a" * 64,
            error="A previous pass stopped.",
        )
    )
    await db_session.flush()

    result = await scan(db_session, Settings(_env_file=None, import_staging_dir=tmp_path), qbittorrent=None)

    assert result.found == int(status is MediaImportStatus.FAILED)
    assert result.already_known == int(status is not MediaImportStatus.FAILED)


async def test_superseded_history_does_not_block_a_new_row(db_session: AsyncSession, tmp_path: Path) -> None:
    source = media_file(tmp_path / "film.mkv")
    replacement = MediaImport(
        source=MediaImportSource.MANUAL,
        source_path=str(tmp_path / "old.mkv"),
        original_name="old.mkv",
        size_bytes=MEDIA_IMPORT_MIN_BYTES,
        status=MediaImportStatus.FOUND,
    )
    db_session.add(replacement)
    await db_session.flush()
    db_session.add(
        MediaImport(
            source=MediaImportSource.STAGING_FOLDER,
            source_path=str(source.resolve()),
            original_name=source.name,
            size_bytes=MEDIA_IMPORT_MIN_BYTES,
            status=MediaImportStatus.FOUND,
            superseded_at=utcnow(),
            superseded_by_id=replacement.id,
        )
    )
    await db_session.flush()

    result = await scan(db_session, Settings(_env_file=None, import_staging_dir=tmp_path), qbittorrent=None)

    assert result.found == 1
    assert result.already_known == 0
    assert (await db_session.scalar(select(func.count()).select_from(MediaImport))) == 3


@pytest.mark.parametrize("nested", [False, True], ids=["root-save-path", "nested-save-path"])
async def test_qbittorrent_paths_use_save_path_not_content_path(
    db_session: AsyncSession, tmp_path: Path, nested: bool
) -> None:
    save_path = tmp_path / "downloads" if nested else tmp_path
    expected: set[str] = set()
    for file in fixture_rows(QBITTORRENT, MULTI_FILE_FIXTURE):
        path = media_file(save_path / str(file["name"]), int(str(file["size"])))
        if path.stat().st_size >= MEDIA_IMPORT_MIN_BYTES:
            expected.add(str(path.resolve()))
    client, responder = qbittorrent_client_for(
        httpx.Response(200, json=[_torrent(save_path)]), fixture_response(QBITTORRENT, MULTI_FILE_FIXTURE)
    )
    try:
        result = await scan(db_session, Settings(_env_file=None, import_staging_dir=tmp_path), qbittorrent=client)
    finally:
        await client.aclose()

    rows = (await db_session.scalars(select(MediaImport))).all()
    assert {row.source_path for row in rows} == expected
    assert all(row.source is MediaImportSource.QBITTORRENT_COMPLETED for row in rows)
    assert result.found == 2
    assert result.candidates_seen == 3
    assert result.too_small == 1
    assert result.qbittorrent_reachable is True
    assert result.qbittorrent_outside_staging == 0
    assert len(responder.requests) == 4


@pytest.mark.parametrize("kind", ["outside", "relative", "empty", "symlink"], ids=str)
async def test_unsafe_qbittorrent_save_paths_are_reported_without_listing_files(
    db_session: AsyncSession, tmp_path: Path, kind: str
) -> None:
    root = tmp_path / "staging"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    link = root / "escape"
    link.symlink_to(outside, target_is_directory=True)
    values = {"outside": str(outside), "relative": "relative", "empty": "", "symlink": str(link)}
    client, responder = qbittorrent_client_for(httpx.Response(200, json=[_torrent(root) | {"save_path": values[kind]}]))
    try:
        result = await scan(db_session, Settings(_env_file=None, import_staging_dir=root), qbittorrent=client)
    finally:
        await client.aclose()

    assert result.qbittorrent_outside_staging == 1
    assert result.qbittorrent_reachable is True
    assert result.found == 0
    assert len(responder.requests) == 3


async def test_qbittorrent_failure_discards_earlier_peer_results_and_keeps_staging(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    file_rows = fixture_rows(QBITTORRENT, MULTI_FILE_FIXTURE)
    source = media_file(tmp_path / str(file_rows[0]["name"]))
    client, _ = qbittorrent_client_for(
        httpx.Response(200, json=[_torrent(tmp_path), _torrent(tmp_path, 1)]),
        httpx.Response(200, json=[file_rows[0]]),
        httpx.Response(503),
    )
    try:
        result = await scan(db_session, Settings(_env_file=None, import_staging_dir=tmp_path), qbittorrent=client)
    finally:
        await client.aclose()

    row = (await db_session.scalars(select(MediaImport))).one()
    assert result.qbittorrent_reachable is False
    assert result.found == 1
    assert row.source is MediaImportSource.STAGING_FOLDER
    assert row.source_path == str(source.resolve())


@pytest.mark.parametrize("configured", [False, True], ids=["unconfigured", "no-staging-root"])
async def test_disabled_scan_arms_make_no_requests(db_session: AsyncSession, tmp_path: Path, configured: bool) -> None:
    client, responder = qbittorrent_client_for(base_url=None if not configured else "http://127.0.0.1:8080")
    settings = Settings(_env_file=None, import_staging_dir=None if configured else tmp_path)
    try:
        result = await scan(db_session, settings, qbittorrent=client)
    finally:
        await client.aclose()

    assert result.qbittorrent_reachable is False
    assert result.found == result.candidates_seen == 0
    assert responder.requests == []
    assert result.staging_dir == ("" if configured else str(tmp_path.resolve()))


async def test_unrecognised_hash_is_skipped_but_v1_and_v2_continue(
    db_session: AsyncSession, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    torrents = [_torrent(tmp_path) | {"hash": "unexpected\nforged=log"}, _torrent(tmp_path), _torrent(tmp_path, 2)]
    client, responder = qbittorrent_client_for(
        httpx.Response(200, json=torrents), httpx.Response(200, json=[]), httpx.Response(200, json=[])
    )
    try:
        with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
            result = await scan(db_session, Settings(_env_file=None, import_staging_dir=tmp_path), qbittorrent=client)
    finally:
        await client.aclose()

    assert result.qbittorrent_reachable is True
    assert [request.url.params["hash"] for request in responder.requests if "hash" in request.url.params] == [
        torrents[1]["hash"],
        torrents[2]["hash"],
    ]
    assert "skipped=unrecognised_hash" in caplog.text
    assert "forged=log" not in caplog.text


async def test_a_pass_that_found_nothing_logs_its_counts(
    db_session: AsyncSession, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        result = await scan(db_session, Settings(_env_file=None, import_staging_dir=tmp_path), qbittorrent=None)

    messages = [record.getMessage() for record in caplog.records if record.name == LOGGER_NAME]
    assert len(messages) == 2
    assert "outcome=started" in messages[0]
    assert "outcome=finished" in messages[1]
    for field in result.model_fields_set - {"staging_dir", "qbittorrent_reachable"}:
        assert f"{field}=0" in messages[1]


@pytest.mark.parametrize("kind", ["missing", "file", "invalid"], ids=str)
async def test_an_unreadable_staging_root_is_reported(db_session: AsyncSession, tmp_path: Path, kind: str) -> None:
    roots = {"missing": tmp_path / "missing", "file": media_file(tmp_path / "file.mkv"), "invalid": Path("\0")}

    result = await scan(db_session, Settings(_env_file=None, import_staging_dir=roots[kind]), qbittorrent=None)

    assert result.unreadable == 1
    assert result.found == 0


async def test_a_scan_does_not_change_either_media_or_workbooks(
    db_session: AsyncSession, tmp_path: Path, library: Path
) -> None:
    staging = tmp_path / "staging"
    source = media_file(staging / "film.mkv")
    before = {path.name: path.read_bytes() for path in library.glob("*.xlsx")}
    stamp = source.stat().st_mtime_ns

    await scan(
        db_session,
        Settings(_env_file=None, library_dir=library, import_staging_dir=staging),
        qbittorrent=None,
    )

    assert {path.name: path.read_bytes() for path in library.glob("*.xlsx")} == before
    assert source.stat().st_mtime_ns == stamp
    assert source.stat().st_size == MEDIA_IMPORT_MIN_BYTES
    assert list(staging.iterdir()) == [source]


async def test_walk_resolve_and_stat_run_off_the_event_loop(
    db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    media_file(tmp_path / "film.mkv")
    main_thread = threading.get_ident()
    worker_threads: list[int] = []
    real_walk, real_stat, real_resolve = os.walk, Path.stat, Path.resolve

    def observed_walk(
        root: Path, *, followlinks: bool, onerror: Callable[[OSError], None]
    ) -> Iterator[tuple[str, list[str], list[str]]]:
        worker_threads.append(threading.get_ident())
        yield from real_walk(root, followlinks=followlinks, onerror=onerror)

    def observed_stat(path: Path, *, follow_symlinks: bool = True) -> os.stat_result:
        worker_threads.append(threading.get_ident())
        return real_stat(path, follow_symlinks=follow_symlinks)

    def observed_resolve(path: Path, strict: bool = False) -> Path:
        worker_threads.append(threading.get_ident())
        return real_resolve(path, strict=strict)

    settings = Settings(_env_file=None, import_staging_dir=tmp_path)
    with monkeypatch.context() as patch:
        patch.setattr(os, "walk", observed_walk)
        patch.setattr(Path, "stat", observed_stat)
        patch.setattr(Path, "resolve", observed_resolve)
        result = await scan(db_session, settings, qbittorrent=None)

    assert result.found == 1
    assert worker_threads
    assert all(thread != main_thread for thread in worker_threads)


@pytest.mark.parametrize("commit", [True, False], ids=["commit", "rollback"])
async def test_concurrent_scans_wait_until_the_first_callers_transaction_ends(
    engine: AsyncEngine, tmp_path: Path, commit: bool
) -> None:
    source = media_file(tmp_path / "film.mkv")
    settings = Settings(_env_file=None, import_staging_dir=tmp_path)
    async with AsyncSession(engine, expire_on_commit=False) as first, AsyncSession(engine) as second:
        assert (await scan(first, settings, qbittorrent=None)).found == 1
        waiting = asyncio.create_task(scan(second, settings, qbittorrent=None))
        try:
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(asyncio.shield(waiting), timeout=LOCK_WAIT_SECONDS)
            if commit:
                await first.commit()
            else:
                await first.rollback()
            result = await asyncio.wait_for(waiting, timeout=LOCK_RELEASE_SECONDS)
            assert result.found == int(not commit)
            assert result.already_known == int(commit)
            await second.commit()
        finally:
            if not waiting.done():
                waiting.cancel()
                await asyncio.gather(waiting, return_exceptions=True)
            await first.rollback()
            await second.rollback()
            async with AsyncSession(engine) as cleanup:
                await cleanup.execute(delete(MediaImport).where(MediaImport.source_path == str(source.resolve())))
                await cleanup.commit()
