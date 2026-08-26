from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

from library_choice import (
    ORDER_HEADER_WORD,
    another_category,
    the_category_whose_order_column_is_not_headed_order,
)
from tv_watchlist.constants import DEFAULT_ACCENT_RGB, ORDER_HEADER_ALIASES, TEMP_WRITE_PREFIX
from tv_watchlist.workbook.backup import snapshot
from tv_watchlist.workbook.cells import cell_text
from tv_watchlist.workbook.discovery import resolve, workbook_paths
from tv_watchlist.workbook.errors import CategoryNotFoundError
from tv_watchlist.workbook.locking import excel_lock_path, is_locked_by_excel
from tv_watchlist.workbook.reader import read_category
from tv_watchlist.workbook.schema import build_columns, normalize_header, parse_choices
from tv_watchlist.workbook.writer import add_watch_column

BACKUP_INTERVAL = 900.0
RETENTION = 10
STALE_BACKUP_COUNT = 4


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, ""),
        (True, "TRUE"),
        (False, "FALSE"),
        (dt.date(2013, 4, 6), "2013-04-06"),
        (dt.datetime(2013, 4, 6), "2013-04-06"),
        (dt.datetime(2013, 4, 6, 21, 30), "2013-04-06 21:30:00"),
        (7.0, "7"),
        (7.5, "7.5"),
        (12, "12"),
        ("Watched", "Watched"),
    ],
)
def test_cell_text_renders_every_excel_value_type(value: object, expected: str) -> None:
    assert cell_text(value) == expected


@pytest.mark.parametrize(
    ("formula", "expected"),
    [
        ('",Watched,In progress,Skip"', ["", "Watched", "In progress", "Skip"]),
        ("=$A$1:$A$4", []),
        (None, []),
        ("", []),
    ],
)
def test_parse_choices_only_accepts_inline_lists(formula: str | None, expected: list[str]) -> None:
    assert parse_choices(formula) == expected


def test_workbook_paths_ignores_excel_scratch_files(subject_path: Path, library: Path) -> None:
    excel_lock_path(subject_path).write_bytes(b"owner")
    (library / f"{TEMP_WRITE_PREFIX}{subject_path.stem}.tmp").write_bytes(b"partial")
    names = {path.name for path in workbook_paths(library)}
    assert not any(name.startswith(("~$", ".")) for name in names)


def test_workbook_paths_of_a_missing_directory_is_empty(tmp_path: Path) -> None:
    assert workbook_paths(tmp_path / "nope") == []


def test_resolving_an_unknown_id_raises(library: Path) -> None:
    with pytest.raises(CategoryNotFoundError):
        resolve(library, "not-a-category")


def test_excel_owner_file_marks_a_workbook_locked(subject_path: Path) -> None:
    assert is_locked_by_excel(subject_path) is False
    excel_lock_path(subject_path).write_bytes(b"owner")
    assert is_locked_by_excel(subject_path) is True


def test_backup_snapshots_once_per_process_and_prunes(subject_path: Path, library: Path, tmp_path: Path) -> None:
    backup_dir = tmp_path / "backups"

    assert snapshot(subject_path, backup_dir, retention=2, interval_seconds=BACKUP_INTERVAL) is not None
    assert snapshot(subject_path, backup_dir, retention=2, interval_seconds=BACKUP_INTERVAL) is None

    for index in range(STALE_BACKUP_COUNT):
        (backup_dir / f"{subject_path.stem}__2024010{index}-000000.xlsx").write_bytes(b"old")
    other = another_category().copied_into(library)
    assert snapshot(other, backup_dir, retention=2, interval_seconds=BACKUP_INTERVAL) is not None
    assert len(list(backup_dir.glob(f"{subject_path.stem}__*.xlsx"))) == STALE_BACKUP_COUNT + 1


def test_a_blank_header_ends_the_grid(tmp_path: Path) -> None:
    """A stray cell to the right of the headers is not a column of the watch order."""
    path = tmp_path / "Odd_Master_Watch_Order.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    for index, header in enumerate(["Order", "Title", "", "scratch note"], start=1):
        sheet.cell(row=1, column=index).value = header
    workbook.save(path)

    columns = build_columns(load_workbook(path).worksheets[0])
    assert [column.key for column in columns] == ["order", "title"]


def test_duplicate_headers_get_distinct_keys(tmp_path: Path) -> None:
    path = tmp_path / "Twin_Master_Watch_Order.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    for index, header in enumerate(["Title", "Title", "Notes"], start=1):
        sheet.cell(row=1, column=index).value = header
    workbook.save(path)

    columns = build_columns(load_workbook(path).worksheets[0])
    assert [column.key for column in columns] == ["title", "title-2", "notes"]
    assert [column.index for column in columns] == [1, 2, 3]


def test_a_sheet_with_no_header_fill_falls_back_to_the_default_accent(tmp_path: Path) -> None:
    path = tmp_path / "Plain_Master_Watch_Order.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.cell(row=1, column=1).value = "Title"
    sheet.cell(row=2, column=1).value = "Something"
    workbook.save(path)

    assert read_category(path).accent == f"#{DEFAULT_ACCENT_RGB[2:]}"


def test_add_watch_column_styles_a_sheet_that_has_no_columns_to_copy(tmp_path: Path) -> None:
    path = tmp_path / "Bare_Master_Watch_Order.xlsx"
    workbook = Workbook()
    workbook.active.cell(row=2, column=1).value = "orphan row"
    workbook.save(path)

    add_watch_column(path)

    sheet = load_workbook(path).worksheets[0]
    assert sheet.cell(row=1, column=2).value == "Watched?"
    assert sheet.cell(row=1, column=2).font.bold is True


@pytest.mark.parametrize(
    ("label", "expected"),
    [("Watched?", "watched"), ("#", "#"), ("When to Watch", "when to watch"), ("Genre / Vibe", "genre  vibe")],
)
def test_header_normalisation_keeps_the_order_hash(label: str, expected: str) -> None:
    from tv_watchlist.workbook.schema import normalize_header

    assert normalize_header(label) == expected


def test_a_sheet_numbering_its_rows_under_a_symbol_still_reads_as_an_order_column(library: Path) -> None:
    facts = the_category_whose_order_column_is_not_headed_order()
    detail = read_category(facts.copied_into(library))

    order = next(column for column in detail.columns if column.role == "order")

    assert order.label == facts.order_label
    assert order.label != ORDER_HEADER_WORD
    assert normalize_header(order.label) in ORDER_HEADER_ALIASES
    assert detail.rows[0].cells[order.key] == "1"


def test_backups_roll_over_time_rather_than_once_per_process(subject_path: Path, tmp_path: Path) -> None:
    backup_dir = tmp_path / "rolling"

    assert snapshot(subject_path, backup_dir, retention=RETENTION, interval_seconds=BACKUP_INTERVAL) is not None
    assert snapshot(subject_path, backup_dir, retention=RETENTION, interval_seconds=BACKUP_INTERVAL) is None
    assert snapshot(subject_path, backup_dir, retention=RETENTION, interval_seconds=0.0) is not None
