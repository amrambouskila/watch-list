from __future__ import annotations

import ctypes
import errno
import os
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from tv_watchlist.models.import_file_identity import ImportFileIdentity
from tv_watchlist.services import import_source_lock as subject
from tv_watchlist.services.import_source_lock import ImportSourceLock


def test_lock_is_nonblocking_and_released(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.write_bytes(b"abc")
    identity = ImportFileIdentity.from_stat(source.stat())
    first, second = ImportSourceLock(source, identity), ImportSourceLock(source, identity)
    try:
        assert first.acquire()
        assert not second.acquire()
        first.release()
        assert second.acquire()
    finally:
        first.release()
        second.release()
    assert source.read_bytes() == b"abc"


def test_replaced_source_cannot_be_claimed(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.write_bytes(b"abc")
    identity = ImportFileIdentity.from_stat(source.stat())
    source.rename(tmp_path / "original")
    source.write_bytes(b"replacement")
    lock = ImportSourceLock(source, identity)
    try:
        with pytest.raises(OSError, match="identity"):
            lock.acquire()
    finally:
        lock.release()


def test_unsupported_lock_is_an_explicit_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import fcntl

    path = tmp_path / "source"
    path.write_bytes(b"abc")
    lock = ImportSourceLock(path, ImportFileIdentity.from_stat(path.stat()))

    def unsupported(descriptor: int, flags: int) -> None:
        raise OSError(errno.ENOTSUP, "filesystem has no locks")

    monkeypatch.setattr(fcntl, "flock", unsupported)
    with pytest.raises(OSError, match="no locks"):
        lock.acquire()
    assert lock.descriptor is None


@pytest.mark.parametrize("failure", ["none", "create", "convert", "lock"])
def test_windows_adapter_opens_readonly_share_delete_and_locks_beyond_eof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    path = tmp_path / "source"
    path.write_bytes(b"abc")
    lock = ImportSourceLock(path, ImportFileIdentity.from_stat(path.stat()))
    calls: list[tuple[object, ...]] = []

    def create(*args: object) -> int:
        calls.append(args)
        return ctypes.c_void_p(-1).value if failure == "create" else os.open(path, os.O_RDONLY)

    def close(handle: int) -> int:
        os.close(handle)
        return 1

    def convert(handle: int, flags: int) -> int:
        if failure == "convert":
            raise OSError("conversion failed")
        return handle

    def locking(descriptor: int, mode: int, count: int) -> None:
        assert os.lseek(descriptor, 0, os.SEEK_CUR) == 3
        assert (mode, count) == (2, 1)
        if failure == "lock":
            raise OSError(errno.EACCES, "already locked")

    crt = ModuleType("msvcrt")
    crt.open_osfhandle = convert
    crt.locking = locking
    crt.LK_NBLCK = 2
    monkeypatch.setitem(sys.modules, "msvcrt", crt)
    monkeypatch.setattr(subject.sys, "platform", "win32")
    monkeypatch.setattr(
        ctypes, "WinDLL", lambda *args, **kwargs: SimpleNamespace(CreateFileW=create, CloseHandle=close), raising=False
    )
    monkeypatch.setattr(ctypes, "get_last_error", lambda: errno.EACCES, raising=False)
    monkeypatch.setattr(ctypes, "WinError", lambda code: OSError(code, "CreateFile failed"), raising=False)
    try:
        if failure in ("create", "convert"):
            with pytest.raises(OSError):
                lock.acquire()
        else:
            assert lock.acquire() == (failure == "none")
        assert calls[0][1] == 0x80000000
        assert calls[0][2] == 7
        assert calls[0][4] == 3
        assert path.read_bytes() == b"abc"
    finally:
        lock.release()
