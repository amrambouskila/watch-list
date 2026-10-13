"""The SQL tap: every statement one engine issues, captured while a block runs.

One copy, at the tests root, because three suites want it for different reasons - the ingest suites
count the writes against a named table, and T28's service suite counts a page's whole cost to prove
there is no N+1. A second copy is always the one that drifts (CLAUDE.md section 7).

Bound to **one engine**, never to the `Engine` class: a class-level listener captures every engine in
the process, so a figure it reports is only accidentally about the session under test.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine


def statements_against(engine: AsyncEngine, table: str | None = None) -> tuple[list[str], Callable[..., None]]:
    """Every SQL statement this engine issues, or only those naming one table, plus the handler to remove.

    The caller owns the teardown (`event.remove(engine.sync_engine, "before_cursor_execute", handler)`);
    `counted_statements` below does it for you when the capture is scoped to a block.
    """
    seen: list[str] = []
    pattern = re.compile(rf"\b{table}\b") if table is not None else None

    def record(_connection: object, _cursor: object, statement: str, *_rest: object) -> None:
        if pattern is None or pattern.search(statement.lower()):
            seen.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", record)
    return seen, record


@contextmanager
def counted_statements(engine: AsyncEngine, table: str | None = None) -> Iterator[list[str]]:
    """The same tap, scoped to a block, so an N+1 shows up as a count that grows with the page."""
    seen, handler = statements_against(engine, table)
    try:
        yield seen
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", handler)
