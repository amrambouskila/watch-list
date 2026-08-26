"""Say what each category's artwork is, in the artwork table, without touching a row this app did not write."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final

from tv_watchlist.constants import TEMP_WRITE_PREFIX, TEMP_WRITE_SUFFIX
from tv_watchlist.models.hero_candidate import HeroCandidate

TABLE_HEADER: Final[str] = "| Category | Source file | Licence | Page |"
TABLE_SEPARATOR: Final[str] = "|---|---|---|---|"
ROW_OPEN: Final[str] = "| "
ROW_CLOSE: Final[str] = " |"
CELL_SEPARATOR: Final[str] = " | "
PIPE: Final[str] = "|"
ESCAPED_PIPE: Final[str] = r"\|"
BACKSLASH: Final[str] = "\\"
ESCAPED_BACKSLASH: Final[str] = r"\\"
CRLF: Final[bytes] = b"\r\n"
LF: Final[bytes] = b"\n"
FIRST_CELL: Final[int] = 0


def _cell(value: str) -> str:
    """One table cell: no newline may split the row in two, and no pipe may forge a column."""
    # Backslashes go first. Escaping only the pipe puts a backslash in front of a backslash the
    # value already carried, and that pair is itself an escape -- leaving the pipe behind it free to
    # open a column after all.
    flattened = " ".join(value.split()).replace(BACKSLASH, ESCAPED_BACKSLASH)
    return flattened.replace(PIPE, ESCAPED_PIPE)


def _row_for(category_name: str, candidate: HeroCandidate) -> str:
    """The single row this app files one category's artwork under."""
    cells = (category_name, candidate.source_file, candidate.licence, candidate.page)
    return ROW_OPEN + CELL_SEPARATOR.join(_cell(cell) for cell in cells) + ROW_CLOSE


def _credits(line: str, category_cell: str) -> bool:
    """True when this line is the row this app itself wrote for that category."""
    # The separator row cannot open with "| " at all; only the header could be read as a category.
    if not line.startswith(ROW_OPEN) or line == TABLE_HEADER:
        return False
    return line.removeprefix(ROW_OPEN).split(CELL_SEPARATOR)[FIRST_CELL] == category_cell


def _superseded(existing: bytes, category_cell: str) -> int | None:
    """Which line already credits that category, or None when the table says nothing about it yet."""
    for index, line in enumerate(existing.splitlines()):
        if _credits(line.decode("utf-8"), category_cell):
            return index
    return None


def _swapped_in(path: Path, content: bytes) -> None:
    """Write beside the table and swap, so a failure mid-write never truncates the credits."""
    temp = path.parent / f"{TEMP_WRITE_PREFIX}{os.getpid()}-{path.stem}{TEMP_WRITE_SUFFIX}"
    try:
        temp.write_bytes(content)
        os.replace(temp, path)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise


def _appended(existing: bytes, row: str, ending: bytes) -> bytes:
    """The bytes that go under the table so it gains a first credit for this category."""
    lines = [] if existing else [TABLE_HEADER, TABLE_SEPARATOR]
    lines.append(row)
    unterminated = b"" if not existing or existing.endswith(LF) else ending
    return unterminated + b"".join(line.encode("utf-8") + ending for line in lines)


def _rewritten(existing: bytes, superseded: int, row: str, ending: bytes) -> bytes:
    """The table with one line replaced in place; every other byte is carried across untouched."""
    lines = existing.splitlines(keepends=True)
    stale = lines[superseded]
    kept_ending = stale[len(stale.rstrip(CRLF)) :]
    lines[superseded] = row.encode("utf-8") + (kept_ending or ending)
    return b"".join(lines)


def credit_hero_row(path: Path, category_name: str, candidate: HeroCandidate) -> None:
    """
    Leave the table crediting exactly this image for this category, and holding no other row for it.

    A re-pick supersedes its own earlier credit rather than adding a second, so the table says what a
    category's artwork *is*. Only that one line may change: rows the owner wrote by hand -- including
    a row for the same category under their own spelling -- are never what this matches.
    """
    existing = path.read_bytes() if path.is_file() else b""
    ending = CRLF if CRLF in existing else LF
    row = _row_for(category_name, candidate)
    superseded = _superseded(existing, _cell(category_name))
    if superseded is None:
        # Appending, rather than rewriting, is what makes "existing rows untouched" a property of a
        # first credit itself instead of a property of this function being careful.
        with path.open("ab") as handle:
            handle.write(_appended(existing, row, ending))
        return
    _swapped_in(path, _rewritten(existing, superseded, row, ending))
