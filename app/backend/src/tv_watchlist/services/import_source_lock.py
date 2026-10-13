"""A nonblocking source-inode lock that survives loss of the database connection."""

from __future__ import annotations

import ctypes
import errno
import os
import sys
from pathlib import Path

from tv_watchlist.constants import (
    IMPORT_WIN_GENERIC_READ,
    IMPORT_WIN_OPEN_EXISTING,
    IMPORT_WIN_OPEN_REPARSE_POINT,
    IMPORT_WIN_SHARE_READ_WRITE_DELETE,
)
from tv_watchlist.models.import_file_identity import ImportFileIdentity


class ImportSourceLock:
    def __init__(self, path: Path, identity: ImportFileIdentity) -> None:
        self.path, self.identity = path, identity
        self.descriptor: int | None = None

    def acquire(self) -> bool:
        """Claim the expected inode without writing bytes or waiting for another worker."""
        self.descriptor = (
            self._windows_open()
            if sys.platform == "win32"
            else os.open(self.path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        )
        try:
            if sys.platform == "win32":
                import msvcrt

                # CRT locking may extend beyond EOF without modifying the file; this avoids locking media bytes.
                # learn.microsoft.com/en-us/cpp/c-runtime-library/reference/locking
                os.lseek(self.descriptor, self.identity.size_bytes, os.SEEK_SET)
                msvcrt.locking(self.descriptor, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if ImportFileIdentity.from_stat(os.fstat(self.descriptor)) != self.identity:
                raise OSError("Staging source identity changed before ownership was acquired")
        except OSError as error:
            self.release()
            if error.errno in (errno.EACCES, errno.EAGAIN):
                return False
            raise
        return True

    def release(self) -> None:
        if self.descriptor is not None:
            descriptor, self.descriptor = self.descriptor, None
            os.close(descriptor)

    def _windows_open(self) -> int:
        import msvcrt

        # FILE_SHARE_DELETE lets confirmed cleanup unlink while ownership remains held until close.
        # learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        create = kernel.CreateFileW
        create.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_void_p,
        ]
        create.restype = ctypes.c_void_p
        handle = create(
            str(self.path),
            IMPORT_WIN_GENERIC_READ,
            IMPORT_WIN_SHARE_READ_WRITE_DELETE,
            None,
            IMPORT_WIN_OPEN_EXISTING,
            IMPORT_WIN_OPEN_REPARSE_POINT,
            None,
        )
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return msvcrt.open_osfhandle(handle, os.O_RDONLY)
        except OSError:
            close = kernel.CloseHandle
            close.argtypes, close.restype = [ctypes.c_void_p], ctypes.c_int
            close(handle)
            raise
