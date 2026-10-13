"""Atomic no-overwrite publication using the host's native rename primitive."""

from __future__ import annotations

import ctypes
import errno
import os
import sys
from pathlib import Path

from tv_watchlist.constants import IMPORT_AT_FDCWD_LINUX, IMPORT_RENAME_EXCL_DARWIN, IMPORT_RENAME_NOREPLACE_LINUX


def rename_exclusive(source: Path, destination: Path) -> None:
    """Rename or refuse; never emulate exclusion with an exists check plus replacement."""
    # APIs: docs.python.org/3/library/os.html#os.rename; man7.org/linux/man-pages/man2/rename.2.html;
    # github.com/apple-oss-distributions/xnu/blob/main/bsd/sys/stdio.h (RENAME_EXCL).
    if sys.platform == "win32":
        os.rename(source, destination)
        return
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin" and hasattr(libc, "renamex_np"):
        rename = libc.renamex_np
        rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        result = rename(os.fsencode(source), os.fsencode(destination), IMPORT_RENAME_EXCL_DARWIN)
    elif sys.platform == "linux" and hasattr(libc, "renameat2"):
        rename = libc.renameat2
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        result = rename(
            IMPORT_AT_FDCWD_LINUX,
            os.fsencode(source),
            IMPORT_AT_FDCWD_LINUX,
            os.fsencode(destination),
            IMPORT_RENAME_NOREPLACE_LINUX,
        )
    else:
        raise OSError(errno.ENOTSUP, "Atomic exclusive rename is not supported on this platform")
    if result != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), str(destination))
