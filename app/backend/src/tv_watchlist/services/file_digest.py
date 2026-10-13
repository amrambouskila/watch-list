"""Streaming sha256 for a stable regular file, refusing symlinks."""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

from tv_watchlist.models.import_file_identity import ImportFileIdentity


def sha256_of(path: Path) -> str:
    """Hash a regular file in bounded memory and refuse identity changes during the read."""
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise OSError("Digest requires a regular file")
    with path.open("rb") as handle:
        opened = ImportFileIdentity.from_stat(os.fstat(handle.fileno()))
        if opened != ImportFileIdentity.from_stat(before):
            raise OSError("File changed before hashing")
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
        if opened != ImportFileIdentity.from_stat(os.fstat(handle.fileno())):
            raise OSError("File changed while hashing")
    if opened != ImportFileIdentity.from_stat(path.lstat()):
        raise OSError("File replaced while hashing")
    return digest
