from __future__ import annotations

from pathlib import Path

import pytest

from library_choice import a_category, a_name_the_library_does_not_hold, another_category
from snapshot import fingerprint
from tv_watchlist.constants import FIRST_DATA_ROW, WATCHED
from tv_watchlist.workbook import discovery
from tv_watchlist.workbook.errors import DuplicateCategoryError, InvalidNameError, WorkbookLockedError
from tv_watchlist.workbook.locking import excel_lock_path
from tv_watchlist.workbook.naming import category_id
from tv_watchlist.workbook.reader import read_category
from tv_watchlist.workbook.renaming import rename_workbook
from tv_watchlist.workbook.stem import validate_stem
from workbook_facts import WorkbookFacts

RENAMED_STEM = a_name_the_library_does_not_hold("Renamed_Master_Watch_Order")


@pytest.mark.parametrize(
    "stem",
    ["", "   ", "  . ", 'has"quote', "has/slash", "has\backslash", "has:colon", "has|pipe", "has?mark", "has*star"],
)
def test_names_the_filesystem_would_refuse_are_rejected(stem: str) -> None:
    with pytest.raises(InvalidNameError):
        validate_stem(stem)


@pytest.mark.parametrize("stem", ["CON", "nul", "Com1", "LPT9", "aux.xlsx"])
def test_windows_reserved_device_names_are_rejected(stem: str) -> None:
    with pytest.raises(InvalidNameError):
        validate_stem(stem)


def test_a_typed_xlsx_suffix_is_not_doubled() -> None:
    assert validate_stem("Cowboy_Bebop.xlsx") == "Cowboy_Bebop"
    assert validate_stem("  Cowboy_Bebop  ") == "Cowboy_Bebop"


def test_renaming_moves_the_file_and_leaves_its_contents_alone(subject: WorkbookFacts, subject_path: Path) -> None:
    before = read_category(subject_path)
    structure = fingerprint(subject_path)

    destination = rename_workbook(subject_path, RENAMED_STEM)

    assert not subject_path.exists()
    assert destination.name == f"{RENAMED_STEM}.xlsx"
    after = read_category(destination)
    assert after.name == RENAMED_STEM
    assert after.id == category_id(destination)
    assert after.counts.total == before.counts.total
    assert [row.cells[subject.title_key] for row in after.rows] == [row.cells[subject.title_key] for row in before.rows]
    assert fingerprint(destination) == structure


def test_renaming_preserves_marks_already_made(subject: WorkbookFacts, subject_path: Path) -> None:
    from tv_watchlist.workbook.writer import update_row

    before = read_category(subject_path).counts.watched
    update_row(subject_path, FIRST_DATA_ROW, {subject.watch_key: WATCHED})

    destination = rename_workbook(subject_path, RENAMED_STEM)

    assert read_category(destination).counts.watched == before + 1


def test_renaming_onto_an_existing_workbook_is_refused(subject_path: Path) -> None:
    occupied = another_category()
    with pytest.raises(DuplicateCategoryError):
        rename_workbook(subject_path, occupied.stem)
    assert subject_path.exists()


def test_renaming_to_the_same_name_is_a_no_op(subject_path: Path) -> None:
    assert rename_workbook(subject_path, subject_path.stem) == subject_path
    assert subject_path.exists()


def test_a_workbook_open_in_excel_cannot_be_renamed(subject_path: Path) -> None:
    excel_lock_path(subject_path).write_bytes(b"owner")
    with pytest.raises(WorkbookLockedError):
        rename_workbook(subject_path, RENAMED_STEM)
    assert subject_path.exists()


RENAME_TARGETS = [
    a_name_the_library_does_not_hold(candidate)
    for candidate in ("Renamed_Franchise_Comprehensive_Master_Watch_Order", "Cowboy_Bebop", "Spider-Man")
]


@pytest.mark.parametrize("stem", RENAME_TARGETS)
def test_the_name_shown_is_the_new_filename_stem_verbatim(subject_path: Path, stem: str) -> None:
    assert read_category(rename_workbook(subject_path, stem)).name == stem


def test_the_category_a_rename_produces_is_addressed_by_its_new_id(subject_path: Path) -> None:
    """A rename is how the owner renames a category, so the id the app answers to has to follow."""
    before = read_category(subject_path).id

    renamed = read_category(rename_workbook(subject_path, RENAMED_STEM))

    assert renamed.id != before
    assert renamed.id == category_id(Path(f"{RENAMED_STEM}.xlsx"))


def test_two_categories_never_share_the_id_the_app_addresses_them_by() -> None:
    assert a_category().category_id != another_category().category_id


def test_renaming_onto_a_name_another_workbook_already_answers_to_is_refused(subject_path: Path) -> None:
    """A free filename is not a free category: the loser of an id clash is unreachable, not merely hidden."""
    shadowed = another_category()

    with pytest.raises(DuplicateCategoryError):
        rename_workbook(subject_path, shadowed.shadowing_name)

    assert subject_path.exists()
    library = subject_path.parent
    ids = [category_id(path) for path in discovery.workbook_paths(library)]
    assert len(ids) == len(set(ids))


def test_a_rename_that_only_respells_the_same_id_is_still_allowed(subject: WorkbookFacts, subject_path: Path) -> None:
    """The workbook already holding that id is this one, so the guard must not refuse its own rename."""
    respelt = subject.shadowing_name

    destination = rename_workbook(subject_path, respelt)

    assert category_id(destination) == subject.category_id
    assert destination.stem == respelt
