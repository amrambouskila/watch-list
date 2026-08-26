"""The artwork credit table: one row per category, and every hand-written row left exactly as it was."""

from __future__ import annotations

import shutil
from pathlib import Path
from string import punctuation

import pytest

from tv_watchlist.constants import HERO_ATTRIBUTION_FILENAME
from tv_watchlist.models.hero_candidate import HeroCandidate
from tv_watchlist.services.attribution import PIPE, TABLE_HEADER, credit_hero_row

CURATED = Path(__file__).resolve().parents[3] / "heroes" / HERO_ATTRIBUTION_FILENAME
CATEGORY_NAME = "A_Category_Master_Watch_Order"
CANDIDATE = HeroCandidate(
    url="https://upload.wikimedia.org/wikipedia/commons/6/6c/Series_Logo.png",
    source_file="Series Logo.png",
    licence="Public domain",
    page="https://commons.wikimedia.org/wiki/File:Series_Logo.png",
    description="The original logotype.",
)


@pytest.fixture
def curated(tmp_path: Path) -> Path:
    """A throwaway copy of the real credit table, so its format is what the test is measured against."""
    destination = tmp_path / HERO_ATTRIBUTION_FILENAME
    shutil.copy2(CURATED, destination)
    return destination


def rows_of(path: Path) -> list[str]:
    """Every table row in the file, header and separator included."""
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("|")]


def test_the_appended_row_matches_the_columns_the_curated_table_already_uses(curated: Path) -> None:
    credit_hero_row(curated, CATEGORY_NAME, CANDIDATE)

    assert rows_of(curated)[-1] == (
        f"| {CATEGORY_NAME} | Series Logo.png | Public domain "
        "| https://commons.wikimedia.org/wiki/File:Series_Logo.png |"
    )


def test_exactly_one_row_is_added(curated: Path) -> None:
    before = len(rows_of(curated))

    credit_hero_row(curated, CATEGORY_NAME, CANDIDATE)

    assert len(rows_of(curated)) == before + 1


def test_every_byte_that_was_already_there_is_still_there_unchanged(curated: Path) -> None:
    original = CURATED.read_bytes()

    credit_hero_row(curated, CATEGORY_NAME, CANDIDATE)

    assert curated.read_bytes().startswith(original)


def test_the_row_keeps_the_line_ending_the_file_is_written_in(curated: Path) -> None:
    before = curated.read_bytes()

    credit_hero_row(curated, CATEGORY_NAME, CANDIDATE)

    after = curated.read_bytes()
    assert after.count(b"\r\n") == before.count(b"\r\n") + 1
    assert after.count(b"\n") == after.count(b"\r\n")


def test_a_file_that_is_not_there_yet_gains_the_header_before_its_first_row(tmp_path: Path) -> None:
    fresh = tmp_path / HERO_ATTRIBUTION_FILENAME

    credit_hero_row(fresh, CATEGORY_NAME, CANDIDATE)

    assert rows_of(fresh)[:2] == ["| Category | Source file | Licence | Page |", "|---|---|---|---|"]
    assert len(rows_of(fresh)) == 3


def test_model_text_carrying_a_pipe_or_a_newline_still_lands_as_one_row(curated: Path) -> None:
    before = len(rows_of(curated))
    smuggled = CANDIDATE.model_copy(update={"source_file": "logo.png |---|\n| Forged | forged.png"})

    credit_hero_row(curated, CATEGORY_NAME, smuggled)

    assert len(rows_of(curated)) == before + 1
    assert "forged.png" in rows_of(curated)[-1]


BACKSLASH = "\\"


def cells_of(row: str) -> list[str]:
    """The row split the way a GFM reader splits it: a pipe is a delimiter unless it is escaped."""
    cells: list[str] = [""]
    index = 0
    while index < len(row):
        character = row[index]
        # cmark-gfm consumes a backslash and the ASCII punctuation after it as one unit before it
        # looks for a delimiter, so a doubled backslash leaves the pipe behind it doing its usual job.
        escapes = character == BACKSLASH and index + 1 < len(row) and row[index + 1] in punctuation
        if escapes:
            cells[-1] += row[index : index + 2]
            index += 2
            continue
        if character == PIPE:
            cells.append("")
        else:
            cells[-1] += character
        index += 1
    return cells


def test_model_text_can_never_forge_a_column_however_it_is_escaped(curated: Path) -> None:
    widths = {len(cells_of(line)) for line in rows_of(curated)}
    smuggled = CANDIDATE.model_copy(update={"source_file": r"logo.png \| Forged \| forged.png"})

    credit_hero_row(curated, CATEGORY_NAME, smuggled)

    assert len(cells_of(rows_of(curated)[-1])) in widths


A_SECOND_CANDIDATE = HeroCandidate(
    url="https://upload.wikimedia.org/wikipedia/commons/1/1a/Series_Mark.png",
    source_file="Series Mark.png",
    licence="CC0",
    page="https://commons.wikimedia.org/wiki/File:Series_Mark.png",
    description="A cleaner mark on transparency.",
)
A_THIRD_CANDIDATE = A_SECOND_CANDIDATE.model_copy(update={"source_file": "Series Mark Third.png"})
ANOTHER_CATEGORY_NAME = "Another_Category_Master_Watch_Order"
# The owner writes their own rows by hand under whatever spelling they like; the app files its rows
# under the workbook stem, so the two never collide and a curated row is never the one replaced.
A_HAND_WRITTEN_SPELLING = "A Category"


def rows_for(path: Path, category_name: str) -> list[str]:
    """Every row of the table crediting one category by that exact name."""
    return [line for line in rows_of(path) if line.startswith(f"| {category_name} |")]


def test_re_crediting_a_category_replaces_its_row_instead_of_adding_a_second(curated: Path) -> None:
    credit_hero_row(curated, CATEGORY_NAME, CANDIDATE)
    before = len(rows_of(curated))

    credit_hero_row(curated, CATEGORY_NAME, A_SECOND_CANDIDATE)

    assert len(rows_of(curated)) == before
    assert rows_for(curated, CATEGORY_NAME) == [
        f"| {CATEGORY_NAME} | Series Mark.png | CC0 | https://commons.wikimedia.org/wiki/File:Series_Mark.png |"
    ]


def test_a_category_never_accumulates_rows_however_often_its_artwork_is_re_picked(curated: Path) -> None:
    for candidate in (CANDIDATE, A_SECOND_CANDIDATE, A_THIRD_CANDIDATE, CANDIDATE):
        credit_hero_row(curated, CATEGORY_NAME, candidate)

    assert len(rows_for(curated, CATEGORY_NAME)) == 1


def test_the_replaced_row_keeps_the_place_it_already_held(curated: Path) -> None:
    credit_hero_row(curated, CATEGORY_NAME, CANDIDATE)
    credit_hero_row(curated, ANOTHER_CATEGORY_NAME, CANDIDATE)
    before = rows_of(curated)

    credit_hero_row(curated, CATEGORY_NAME, A_SECOND_CANDIDATE)

    after = rows_of(curated)
    assert [line.split(" | ")[0] for line in after] == [line.split(" | ")[0] for line in before]


def test_re_crediting_one_category_leaves_every_other_row_byte_identical(curated: Path) -> None:
    credit_hero_row(curated, CATEGORY_NAME, CANDIDATE)
    credit_hero_row(curated, ANOTHER_CATEGORY_NAME, CANDIDATE)
    before = rows_of(curated)

    credit_hero_row(curated, CATEGORY_NAME, A_SECOND_CANDIDATE)

    after = rows_of(curated)
    changed = [pair for pair in zip(before, after, strict=True) if pair[0] != pair[1]]
    assert len(changed) == 1
    assert changed[0][0].startswith(f"| {CATEGORY_NAME} |")


def test_a_row_the_app_did_not_write_is_never_the_one_replaced(curated: Path) -> None:
    hand_written = f"| {A_HAND_WRITTEN_SPELLING} | Owner mark.png | CC BY | https://example.org/mark |"
    before = curated.read_bytes()

    credit_hero_row(curated, A_HAND_WRITTEN_SPELLING + " Master Watch Order", CANDIDATE)

    assert hand_written not in rows_of(curated)
    assert curated.read_bytes().startswith(before)


def test_the_curated_prose_above_the_table_survives_a_replacement(curated: Path) -> None:
    preamble = CURATED.read_text(encoding="utf-8").split(TABLE_HEADER)[0]
    credit_hero_row(curated, CATEGORY_NAME, CANDIDATE)

    credit_hero_row(curated, CATEGORY_NAME, A_SECOND_CANDIDATE)

    assert curated.read_text(encoding="utf-8").startswith(preamble)


def test_a_replacement_keeps_the_line_ending_the_file_is_written_in(curated: Path) -> None:
    credit_hero_row(curated, CATEGORY_NAME, CANDIDATE)
    before = curated.read_bytes()

    credit_hero_row(curated, CATEGORY_NAME, A_SECOND_CANDIDATE)

    after = curated.read_bytes()
    assert after.count(b"\r\n") == before.count(b"\r\n")
    assert after.count(b"\n") == after.count(b"\r\n")


def test_a_name_that_only_looks_like_another_after_escaping_is_still_its_own_row(curated: Path) -> None:
    credit_hero_row(curated, CATEGORY_NAME, CANDIDATE)

    credit_hero_row(curated, f"{CATEGORY_NAME} II", A_SECOND_CANDIDATE)

    assert len(rows_for(curated, CATEGORY_NAME)) == 1
    assert len(rows_for(curated, f"{CATEGORY_NAME} II")) == 1
