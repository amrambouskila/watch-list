from __future__ import annotations

import pytest
from openpyxl import Workbook

from tv_watchlist.constants import DEFAULT_WATCH_CHOICES
from tv_watchlist.workbook.ranges import add_choice_validation

WATCH_COLUMN_INDEX = 1
LAST_ROW = 5


@pytest.mark.parametrize(
    ("choices", "expected"),
    [(list(DEFAULT_WATCH_CHOICES), False), (["Watched", "In progress", "Skip"], True)],
    ids=["list-offers-blank", "list-offers-no-blank"],
)
def test_allow_blank_follows_whether_the_list_itself_offers_blank(choices: list[str], expected: bool) -> None:
    sheet = Workbook().active

    add_choice_validation(sheet, WATCH_COLUMN_INDEX, LAST_ROW, choices)

    assert sheet.data_validations.dataValidation[0].allowBlank is expected
