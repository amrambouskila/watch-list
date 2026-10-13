from __future__ import annotations

import hashlib
import tracemalloc
from pathlib import Path
from typing import BinaryIO

import pytest

from tv_watchlist.services.file_digest import sha256_of


def test_sha256_matches_the_published_abc_vector(tmp_path: Path) -> None:
    path = tmp_path / "abc.mkv"
    path.write_bytes(b"abc")
    assert sha256_of(path) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_large_file_is_streamed(tmp_path: Path) -> None:
    path = tmp_path / "large.mkv"
    chunk = b"a" * 1024 * 1024
    reference = hashlib.sha256()
    with path.open("wb") as handle:
        for _ in range(32):
            handle.write(chunk)
            reference.update(chunk)
    tracemalloc.start()
    try:
        assert sha256_of(path) == reference.hexdigest()
        assert tracemalloc.get_traced_memory()[1] < len(chunk) * 2
    finally:
        tracemalloc.stop()


def test_a_symlink_is_not_followed(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_bytes(b"outside")
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(OSError):
        sha256_of(link)


@pytest.mark.parametrize("replacement", [False, True])
def test_mutation_during_hash_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, replacement: bool) -> None:
    path = tmp_path / "file"
    path.write_bytes(b"abc")
    digest = hashlib.file_digest

    def mutate(handle: BinaryIO, name: str) -> object:
        result = digest(handle, name)
        if replacement:
            path.rename(tmp_path / "old")
        path.write_bytes(b"changed")
        return result

    monkeypatch.setattr(hashlib, "file_digest", mutate)
    with pytest.raises(OSError, match="while hashing"):
        sha256_of(path)


def test_mutation_between_stat_and_open_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "file"
    path.write_bytes(b"abc")
    original = Path.open

    def mutate(target: Path, mode: str = "r", *args: object, **kwargs: object) -> BinaryIO:
        if mode == "rb":
            target.write_bytes(b"changed")
        return original(target, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", mutate)
    with pytest.raises(OSError, match="before hashing"):
        sha256_of(path)
