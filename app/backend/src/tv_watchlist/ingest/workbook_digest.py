"""The sha256 over a workbook's public grid that makes a no-op ingest cheap.

Excel rewrites the whole file every time it closes one, so `st_mtime` alone would re-ingest nineteen
workbooks whenever the owner merely looked at them (master plan section 6.5, rule 1). This digest is the
first half of that test: the pass is skipped when it matches and the sheet's identity cells are still
exactly the live rows' ids (`reconciler.identities_intact`); the stamp is recorded, not compared
(Ruling 49).

The Row ID column is excluded, which is what makes minting free: a first ingest writes 996 identities
into nineteen sheets, and the very next pass must still recognise every one of those files as unchanged.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import Final

from tv_watchlist.models.column_spec import ColumnSpec
from tv_watchlist.models.watch_row import WatchRow
from tv_watchlist.workbook.schema import public_columns

# Canonical JSON: sorted keys and no spacing, so neither dict ordering nor a serialiser's whitespace
# decides whether a workbook looks changed. The same shape `clients/transport.payload_digest` uses.
_SEPARATORS: Final[tuple[str, str]] = (",", ":")


def digest_grid(columns: Sequence[ColumnSpec], rows: Sequence[WatchRow]) -> str:
    """sha256 over the public column keys and every row's number and public cells."""
    public = public_columns(list(columns))
    keys = [column.key for column in public]
    # The row number travels with the cells because `curated_entry.sheet_row` stores it: a blank row
    # inserted above the grid moves every row down without changing a single cell, and an ingest that
    # skipped that would leave every stored `sheet_row` pointing one row short for good.
    grid = [[row.row, [row.cells.get(key, "") for key in keys]] for row in rows]
    canonical = json.dumps([keys, grid], sort_keys=True, separators=_SEPARATORS, ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()
