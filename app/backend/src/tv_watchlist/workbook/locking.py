"""Serialise writes per workbook and detect files Excel is holding open."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path

from tv_watchlist.constants import EXCEL_LOCK_PREFIX

_locks: dict[Path, asyncio.Lock] = {}
_registry_guard = threading.Lock()


def lock_for(path: Path) -> asyncio.Lock:
    """The write lock guarding one workbook, created on first use."""
    key = path.resolve()
    with _registry_guard:
        lock = _locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _locks[key] = lock
        return lock


def excel_lock_path(path: Path) -> Path:
    """Path of the owner file Excel drops beside an open workbook."""
    return path.parent / f"{EXCEL_LOCK_PREFIX}{path.name}"


def is_locked_by_excel(path: Path) -> bool:
    """True when the workbook cannot currently be rewritten."""
    if excel_lock_path(path).exists():
        return True
    try:
        with path.open("r+b"):
            return False
    except OSError:
        return True
