"""Filesystem failures remain visible, and discovery never opens media content."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from import_scan_support import media_file
from tv_watchlist.constants import MEDIA_IMPORT_MIN_BYTES
from tv_watchlist.data.enums import MediaImportSource
from tv_watchlist.services.import_discovery import ImportDiscovery


def test_the_filesystem_size_wins_over_the_peers_size(tmp_path: Path) -> None:
    source = media_file(tmp_path / "film.mkv", MEDIA_IMPORT_MIN_BYTES)
    discovery = ImportDiscovery(tmp_path.resolve())

    discovery.collect([source])

    candidate = discovery.candidates[str(source.resolve())]
    assert candidate.size_bytes == MEDIA_IMPORT_MIN_BYTES
    assert candidate.source is MediaImportSource.QBITTORRENT_COMPLETED


def test_a_missing_peer_file_is_counted_as_unreadable(tmp_path: Path) -> None:
    discovery = ImportDiscovery(tmp_path.resolve())

    discovery.collect([tmp_path / "missing.mkv"])

    assert discovery.unreadable == 1
    assert discovery.candidates == {}


def test_a_directory_reported_as_a_peer_file_is_not_a_candidate(tmp_path: Path) -> None:
    directory = tmp_path / "show.mkv"
    directory.mkdir()
    discovery = ImportDiscovery(tmp_path.resolve())

    discovery.collect([directory])

    assert discovery.candidates_seen == 0
    assert discovery.candidates == {}


def test_repeated_escaped_paths_are_refused_once(tmp_path: Path) -> None:
    root = tmp_path / "staging"
    root.mkdir()
    outside = media_file(tmp_path / "film.mkv")
    link = root / "escape.mkv"
    link.symlink_to(outside)
    discovery = ImportDiscovery(root.resolve())

    discovery.collect([link, link])

    assert discovery.path_refused == 1
    assert discovery.candidates_seen == 0


def test_a_symlink_loop_is_unreadable_instead_of_aborting_the_tree(tmp_path: Path) -> None:
    first, second = tmp_path / "first.mkv", tmp_path / "second.mkv"
    first.symlink_to(second)
    second.symlink_to(first)
    media_file(tmp_path / "good.mkv")
    discovery = ImportDiscovery(tmp_path.resolve())

    discovery.collect([])

    assert discovery.unreadable == 2
    assert len(discovery.candidates) == 1


def test_permission_failure_on_one_file_keeps_other_candidates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    denied = media_file(tmp_path / "denied.mkv")
    readable = media_file(tmp_path / "readable.mkv")
    real_stat = Path.stat

    def stat_with_denial(path: Path, *, follow_symlinks: bool = True) -> os.stat_result:
        if path == denied:
            raise PermissionError("denied", str(path))
        return real_stat(path, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(Path, "stat", stat_with_denial)
    discovery = ImportDiscovery(tmp_path.resolve())

    discovery.collect([])

    assert discovery.unreadable == 1
    assert set(discovery.candidates) == {str(readable.resolve())}


def test_resolve_failure_is_counted_without_stopping_discovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    denied = media_file(tmp_path / "denied.mkv")
    readable = media_file(tmp_path / "readable.mkv")
    real_resolve = Path.resolve

    def resolve_with_denial(path: Path, strict: bool = False) -> Path:
        if path == denied:
            raise PermissionError("denied", str(path))
        return real_resolve(path, strict=strict)

    discovery = ImportDiscovery(tmp_path.resolve())
    monkeypatch.setattr(Path, "resolve", resolve_with_denial)

    discovery.collect([])

    assert discovery.unreadable == 1
    assert set(discovery.candidates) == {str(readable.resolve())}


def test_directory_metadata_failure_is_counted_without_stopping_discovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    denied = tmp_path / "denied"
    denied.mkdir()
    readable = media_file(tmp_path / "readable.mkv")
    real_lstat = Path.lstat

    def lstat_with_denial(path: Path) -> os.stat_result:
        if path == denied:
            raise PermissionError("denied", str(path))
        return real_lstat(path)

    monkeypatch.setattr(Path, "lstat", lstat_with_denial)
    discovery = ImportDiscovery(tmp_path.resolve())

    discovery.collect([])

    assert discovery.unreadable == 1
    assert set(discovery.candidates) == {str(readable.resolve())}
