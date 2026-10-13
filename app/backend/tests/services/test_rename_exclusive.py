from __future__ import annotations

import ctypes
from pathlib import Path
from types import SimpleNamespace

import pytest

from tv_watchlist.services import rename_exclusive as subject
from tv_watchlist.services.rename_exclusive import rename_exclusive


def test_native_rename_preserves_bytes(tmp_path: Path) -> None:
    source, destination = tmp_path / "source", tmp_path / "destination"
    source.write_bytes(b"abc")
    rename_exclusive(source, destination)
    assert not source.exists()
    assert destination.read_bytes() == b"abc"


def test_native_rename_never_overwrites(tmp_path: Path) -> None:
    source, destination = tmp_path / "source", tmp_path / "destination"
    source.write_bytes(b"abc")
    destination.write_bytes(b"original")
    with pytest.raises(FileExistsError):
        rename_exclusive(source, destination)
    assert destination.read_bytes() == b"original"
    assert source.read_bytes() == b"abc"


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_native_adapter_signatures(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, platform: str) -> None:
    calls: list[tuple[object, ...]] = []

    def rename(*args: object) -> int:
        calls.append(args)
        return 0

    fake = SimpleNamespace(renameat2=rename, renamex_np=rename)
    monkeypatch.setattr(subject.sys, "platform", platform)
    monkeypatch.setattr(ctypes, "CDLL", lambda *args, **kwargs: fake)
    rename_exclusive(tmp_path / "from", tmp_path / "to")
    assert calls[0][-1] == (1 if platform == "linux" else 4)
    assert len(calls[0]) == (5 if platform == "linux" else 3)


def test_windows_adapter_uses_nonoverwriting_os_rename(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[tuple[Path, Path]] = []
    monkeypatch.setattr(subject.sys, "platform", "win32")
    monkeypatch.setattr(subject.os, "rename", lambda source, destination: calls.append((source, destination)))
    rename_exclusive(tmp_path / "source", tmp_path / "destination")
    assert calls == [(tmp_path / "source", tmp_path / "destination")]


@pytest.mark.parametrize("platform", ["linux", "darwin", "unsupported"])
def test_missing_atomic_primitive_is_refused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, platform: str) -> None:
    monkeypatch.setattr(subject.sys, "platform", platform)
    monkeypatch.setattr(ctypes, "CDLL", lambda *args, **kwargs: SimpleNamespace())
    with pytest.raises(OSError, match="not supported"):
        rename_exclusive(tmp_path / "source", tmp_path / "destination")
