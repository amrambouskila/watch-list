"""What each category was read at, so a proposal's row numbers can be guarded against that same file."""

from __future__ import annotations


class ReadLog:
    """The workbook mtime each category was last read at, within one chat session."""

    def __init__(self) -> None:
        self._mtimes: dict[str, float] = {}

    def record(self, category_id: str, mtime: float) -> None:
        """Stamp a category with the mtime the rows just handed out were read from."""
        self._mtimes[category_id] = mtime

    def mtime_of(self, category_id: str) -> float | None:
        """The mtime this session last read that category at, or None if it never did."""
        return self._mtimes.get(category_id)

    def forget(self, category_id: str) -> None:
        """Drop a category's stamp; one this session never read has none to drop."""
        self._mtimes.pop(category_id, None)
