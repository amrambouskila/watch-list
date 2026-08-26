from __future__ import annotations

from pathlib import Path

import pytest

from library_choice import every_workbook
from tv_watchlist.constants import ILLEGAL_FILENAME_CHARACTERS, WORKBOOK_SUFFIX
from tv_watchlist.workbook.errors import InvalidNameError
from tv_watchlist.workbook.naming import category_id, workbook_filename
from tv_watchlist.workbook.reader import read_category
from workbook_facts import WorkbookFacts


@pytest.mark.parametrize("facts", every_workbook(), ids=lambda facts: facts.category_id)
def test_a_category_is_named_by_its_filename_stem_verbatim(library: Path, facts: WorkbookFacts) -> None:
    path = facts.copied_into(library)
    assert read_category(path).name == path.stem


@pytest.mark.parametrize(
    ("stem", "expected"),
    [
        ("Alpha_Beta_Gamma", "alpha-beta-gamma"),
        ("Zeta_Modern_2001_2026", "zeta-modern-2001-2026"),
        ("Assorted_Animation_Watchlist", "assorted-animation-watchlist"),
    ],
)
def test_category_id_is_untouched_so_hero_images_keep_matching(tmp_path: Path, stem: str, expected: str) -> None:
    assert category_id(tmp_path / f"{stem}{WORKBOOK_SUFFIX}") == expected


@pytest.mark.parametrize("facts", every_workbook(), ids=lambda facts: facts.category_id)
def test_the_id_a_workbook_derives_is_the_id_its_category_answers_to(library: Path, facts: WorkbookFacts) -> None:
    path = facts.copied_into(library)
    assert read_category(path).id == category_id(path)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("ACME_Chronological", "ACME_Chronological.xlsx"),
        ("Spider-Man", "Spider-Man.xlsx"),
        ("Cowboy Bebop", "Cowboy_Bebop.xlsx"),
        ("  Trigun  ", "Trigun.xlsx"),
        ("Assorted   Films", "Assorted_Films.xlsx"),
        ("ACME Chronological Master Watch Order", "ACME_Chronological_Master_Watch_Order.xlsx"),
        ("Alpha-Beta-Gamma!", "Alpha-Beta-Gamma.xlsx"),
    ],
)
def test_a_new_workbook_is_filed_under_the_name_it_was_given(name: str, expected: str) -> None:
    assert workbook_filename(name) == expected


@pytest.mark.parametrize("stem", ["ACME_Chronological", "Spider-Man", "Alpha_Beta_Comprehensive_Watch_Order"])
def test_a_filename_shaped_name_round_trips_to_itself(stem: str) -> None:
    assert Path(workbook_filename(stem)).stem == stem


@pytest.mark.parametrize("character", list(ILLEGAL_FILENAME_CHARACTERS))
def test_characters_the_filesystem_rejects_are_removed(character: str) -> None:
    assert workbook_filename(f"Alpha{character}Beta") == f"Alpha_Beta{WORKBOOK_SUFFIX}"


@pytest.mark.parametrize("name", ["???", "   ", "-", "_", "...", "CON", "nul"])
def test_a_name_the_suffix_used_to_rescue_is_now_refused_outright(name: str) -> None:
    """Without the old suffix these would land as .xlsx, -.xlsx, or a Windows device name."""
    with pytest.raises(InvalidNameError):
        workbook_filename(name)
