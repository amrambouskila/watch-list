"""The change detector: what the digest sees, and the one column it must never see."""

from __future__ import annotations

from pathlib import Path

import pytest
from tv_watchlist.ingest.workbook_digest import digest_grid

from library_choice import every_workbook
from tv_watchlist.constants import IDENTITY_HEADER_LABEL
from tv_watchlist.models.column_spec import ColumnSpec
from tv_watchlist.models.watch_row import WatchRow
from tv_watchlist.workbook.identity import ensure_identity_column, write_row_ids
from tv_watchlist.workbook.naming import slugify
from tv_watchlist.workbook.reader import read_projection
from workbook_facts import WorkbookFacts

SHA256_HEX_LENGTH = 64


def _columns(*labels: str) -> list[ColumnSpec]:
    return [
        ColumnSpec(key=slugify(label), label=label, index=index, kind="text", role="other", choices=[])
        for index, label in enumerate(labels, start=1)
    ]


def _identity_column(index: int) -> ColumnSpec:
    return ColumnSpec(
        key=slugify(IDENTITY_HEADER_LABEL),
        label=IDENTITY_HEADER_LABEL,
        index=index,
        kind="text",
        role="identity",
        choices=[],
    )


def test_the_digest_is_a_sha256_hex_string() -> None:
    digest = digest_grid(_columns("Title"), [WatchRow(row=2, cells={"title": "Max"})])

    assert len(digest) == SHA256_HEX_LENGTH
    assert set(digest) <= set("0123456789abcdef")


def test_the_digest_ignores_the_identity_column() -> None:
    public = _columns("Order", "Title")
    rows = [WatchRow(row=2, cells={"order": "1", "title": "Max"})]

    bare = digest_grid(public, rows)
    with_identity = digest_grid([*public, _identity_column(3)], rows)

    assert with_identity == bare


def test_a_changed_cell_changes_the_digest() -> None:
    public = _columns("Order", "Title")

    before = digest_grid(public, [WatchRow(row=2, cells={"order": "1", "title": "Max"})])
    after = digest_grid(public, [WatchRow(row=2, cells={"order": "1", "title": "Maxx"})])

    assert after != before


def test_reordering_two_rows_changes_the_digest() -> None:
    public = _columns("Title")
    first = WatchRow(row=2, cells={"title": "Max"})
    second = WatchRow(row=3, cells={"title": "The Sound of Music"})

    assert digest_grid(public, [second, first]) != digest_grid(public, [first, second])


def test_a_row_that_moved_down_the_sheet_changes_the_digest() -> None:
    """`sheet_row` is stored, so a row the reader still lists at a new number is a change to ingest."""
    public = _columns("Title")

    before = digest_grid(public, [WatchRow(row=2, cells={"title": "Max"})])
    after = digest_grid(public, [WatchRow(row=5, cells={"title": "Max"})])

    assert after != before


def test_a_renamed_header_changes_the_digest() -> None:
    rows = [WatchRow(row=2, cells={"title": "Max"})]

    assert digest_grid(_columns("Name"), rows) != digest_grid(_columns("Title"), rows)


@pytest.mark.parametrize("facts", every_workbook(), ids=lambda facts: facts.category_id)
def test_minting_identities_into_a_real_workbook_leaves_its_digest_alone(library: Path, facts: WorkbookFacts) -> None:
    path = facts.copied_into(library)
    before = read_projection(path)
    minted = {row.row: f"00000000-0000-4000-8000-{row.row:012d}" for row in before.detail.rows}

    ensure_identity_column(path)
    write_row_ids(path, minted)

    after = read_projection(path)
    assert after.row_ids == minted
    assert digest_grid(after.detail.columns, after.detail.rows) == digest_grid(
        before.detail.columns, before.detail.rows
    )
