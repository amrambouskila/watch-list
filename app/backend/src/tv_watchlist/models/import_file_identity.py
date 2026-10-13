"""Persisted identity of one regular file, including nanosecond modification time."""

from __future__ import annotations

import os

from pydantic import BaseModel, ConfigDict, Field


class ImportFileIdentity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    device: int = Field(ge=0)
    inode: int = Field(ge=0)
    size_bytes: int = Field(ge=0)
    mtime_ns: int

    @classmethod
    def from_stat(cls, metadata: os.stat_result) -> ImportFileIdentity:
        return cls(
            device=metadata.st_dev, inode=metadata.st_ino, size_bytes=metadata.st_size, mtime_ns=metadata.st_mtime_ns
        )

    def same_file(self, other: ImportFileIdentity) -> bool:
        """A writing temp changes size and time, but never its device/inode ownership."""
        return (self.device, self.inode) == (other.device, other.inode)
