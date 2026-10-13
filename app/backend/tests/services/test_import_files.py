from __future__ import annotations

import os
import uuid
from datetime import date
from pathlib import Path
from typing import BinaryIO

import pytest

from tv_watchlist.config import Settings
from tv_watchlist.data.enums import MediaImportOperationPhase, MediaType
from tv_watchlist.data.errors import ImportPathError
from tv_watchlist.data.models import MediaImport, MediaImportOperation, Title
from tv_watchlist.services import import_files
from tv_watchlist.services.import_files import ImportFiles


def _prepared(tmp_path: Path, previous: bytes | None = None) -> tuple[Settings, MediaImportOperation]:
    staging, media = tmp_path / "staging", tmp_path / "media"
    staging.mkdir()
    media.mkdir()
    source = staging / "source.mkv"
    source.write_bytes(b"abc")
    destination = media / "Movies/Film (2020)/Film (2020).mkv"
    if previous is not None:
        destination.parent.mkdir(parents=True)
        destination.write_bytes(previous)
    settings = Settings(_env_file=None, import_staging_dir=staging, media_root=media)
    row = MediaImport(id=uuid.uuid4(), source_path=str(source), size_bytes=3)
    title = Title(name="Film", media_type=MediaType.MOVIE, first_air_date=date(2020, 1, 1))
    return settings, ImportFiles.prepare(settings, row, title, None)


def _copied(settings: Settings, operation: MediaImportOperation) -> ImportFiles:
    operation.temp_identity = ImportFiles(settings, operation).create_temp().model_dump()
    operation.temp_identity = ImportFiles(settings, operation).copy_temp().model_dump()
    operation.phase = MediaImportOperationPhase.COPIED
    return ImportFiles(settings, operation)


@pytest.mark.parametrize("relative", ["", "..", "../outside", "/outside", "a\\b", "."])
def test_journal_paths_must_be_confined_files(tmp_path: Path, relative: str) -> None:
    with pytest.raises(ImportPathError):
        ImportFiles._path(relative, tmp_path)


@pytest.mark.parametrize("outside", [False, True])
def test_symlink_parents_are_refused(tmp_path: Path, outside: bool) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = (tmp_path if outside else root) / "target"
    target.mkdir()
    (root / "link").symlink_to(target, target_is_directory=True)
    with pytest.raises(ImportPathError):
        ImportFiles._path("link/file", root)


def test_nonregular_artifact_is_refused(tmp_path: Path) -> None:
    with pytest.raises(OSError, match="regular"):
        ImportFiles._identity(tmp_path)


def test_unconfigured_roots_refuse_both_boundaries(tmp_path: Path) -> None:
    settings, operation = _prepared(tmp_path)
    settings.media_root = None
    with pytest.raises(ImportPathError):
        ImportFiles(settings, operation)
    with pytest.raises(ImportPathError):
        ImportFiles.prepare(settings, MediaImport(), Title(), None)


@pytest.mark.parametrize("replacement", ["root", "parent"])
def test_cached_paths_are_rechecked_before_install(tmp_path: Path, replacement: str) -> None:
    settings, operation = _prepared(tmp_path)
    files = _copied(settings, operation)
    original = files.media if replacement == "root" else files.destination.parent
    moved = tmp_path / "moved"
    original.rename(moved)
    original.symlink_to(moved, target_is_directory=True)
    with pytest.raises(ImportPathError):
        files.install()
    assert files.source.read_bytes() == b"abc"


def test_unknown_temp_is_not_copied_over(tmp_path: Path) -> None:
    settings, operation = _prepared(tmp_path)
    files = ImportFiles(settings, operation)
    with pytest.raises(OSError, match="ownership"):
        files.copy_temp()


@pytest.mark.parametrize("changed", ["source", "temp"])
def test_copy_rechecks_open_descriptors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changed: str) -> None:
    settings, operation = _prepared(tmp_path)
    operation.temp_identity = ImportFiles(settings, operation).create_temp().model_dump()
    files = ImportFiles(settings, operation)
    target = files.source if changed == "source" else files.temp
    opened = Path.open
    reads = 0

    def replace_before_open(path: Path, mode: str = "r", *args: object, **kwargs: object) -> BinaryIO:
        nonlocal reads
        if path == target and mode in ("rb", "r+b"):
            reads += 1
            if reads == (2 if changed == "source" else 1):
                path.rename(tmp_path / "old")
                path.write_bytes(b"replacement")
        return opened(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", replace_before_open)
    with pytest.raises(OSError, match="before copy"):
        files.copy_temp()


def test_copy_rechecks_temp_after_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings, operation = _prepared(tmp_path)
    operation.temp_identity = ImportFiles(settings, operation).create_temp().model_dump()
    files = ImportFiles(settings, operation)
    copy = import_files.shutil.copyfileobj

    def replace_during_copy(source: BinaryIO, destination: BinaryIO, length: int) -> None:
        copy(source, destination, length)
        files.temp.rename(tmp_path / "old-temp")
        files.temp.write_bytes(b"unknown")

    monkeypatch.setattr(import_files.shutil, "copyfileobj", replace_during_copy)
    with pytest.raises(OSError, match="replaced during copy"):
        files.copy_temp()
    assert files.temp.read_bytes() == b"unknown"


def test_unexpected_destination_is_never_replaced(tmp_path: Path) -> None:
    settings, operation = _prepared(tmp_path)
    files = _copied(settings, operation)
    files.destination.write_bytes(b"unknown")
    with pytest.raises(OSError, match="unexpectedly exists"):
        files.install()
    assert files.destination.read_bytes() == b"unknown"


def test_missing_original_blocks_rollback(tmp_path: Path) -> None:
    settings, operation = _prepared(tmp_path, b"old")
    files = _copied(settings, operation)
    files.destination.unlink()
    with pytest.raises(OSError, match="cannot be located"):
        files.rollback()
    assert files.temp.exists() and files.source.exists()


def test_occupied_original_destination_blocks_archive_restore(tmp_path: Path) -> None:
    settings, operation = _prepared(tmp_path, b"old")
    files = _copied(settings, operation)
    files.archive.parent.mkdir(parents=True)
    os.link(files.destination, files.archive)
    with pytest.raises(OSError, match="occupied"):
        files.rollback()
    assert files.archive.read_bytes() == files.destination.read_bytes() == b"old"


def test_changed_completed_temp_is_retained(tmp_path: Path) -> None:
    settings, operation = _prepared(tmp_path)
    files = _copied(settings, operation)
    files.temp.write_bytes(b"external change")
    with pytest.raises(OSError, match="changed"):
        files.rollback()
    assert files.temp.read_bytes() == b"external change"


def test_windows_directory_sync_does_not_use_unsupported_open(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(import_files.sys, "platform", "win32")

    def forbidden(*args: object) -> int:
        pytest.fail("Python cannot open a Windows directory for fsync")

    monkeypatch.setattr(import_files.os, "open", forbidden)
    ImportFiles._sync_directory(tmp_path)


def test_changed_target_is_refused(tmp_path: Path) -> None:
    settings, operation = _prepared(tmp_path)
    files = ImportFiles(settings, operation)
    row = MediaImport(source_path=str(files.source))
    title = Title(name="Other", media_type=MediaType.MOVIE, first_air_date=date(2020, 1, 1))
    with pytest.raises(OSError, match="target changed"):
        files.verify_target(row, title, None)


def test_rollback_before_archive_leaves_verified_original_untouched(tmp_path: Path) -> None:
    settings, operation = _prepared(tmp_path, b"old")
    files = _copied(settings, operation)
    files.rollback()
    assert files.destination.read_bytes() == b"old"
    assert files.source.read_bytes() == b"abc"
    assert not files.temp.exists()
