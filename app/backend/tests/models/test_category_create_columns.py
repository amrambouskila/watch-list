"""Columns a create request may ask for: the app's own header names are not among them."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tv_watchlist.constants import APP_OWNED_HEADER_ALIASES, IDENTITY_HEADER_LABEL
from tv_watchlist.models.category_create import CategoryCreate
from tv_watchlist.workbook.naming import slugify
from tv_watchlist.workbook.schema import normalize_header

A_CATEGORY_NAME = "Wartime"


@pytest.mark.parametrize("label", ["Row ID", "RowID", "row id", "Row-ID", " Row ID "])
def test_a_column_the_app_owns_is_refused_by_name(label: str) -> None:
    with pytest.raises(ValidationError, match="a column the app owns"):
        CategoryCreate(name=A_CATEGORY_NAME, columns=["Order", "Title", label])


def test_the_refusal_names_the_label_the_request_asked_for() -> None:
    with pytest.raises(ValidationError, match=f"{IDENTITY_HEADER_LABEL}. is a column the app owns"):
        CategoryCreate(name=A_CATEGORY_NAME, columns=[IDENTITY_HEADER_LABEL])


def test_every_app_owned_alias_is_refused_however_it_is_spelt() -> None:
    """The check runs on the app-owned set, so a role added in a later phase is covered by it too."""
    for alias in APP_OWNED_HEADER_ALIASES:
        with pytest.raises(ValidationError, match="a column the app owns"):
            CategoryCreate(name=A_CATEGORY_NAME, columns=[alias.title()])


def test_column_keys_can_no_longer_mint_the_identity_key() -> None:
    accepted = CategoryCreate(name=A_CATEGORY_NAME, columns=["Order", "Title", "Rows", "Row IDs"])

    assert slugify(IDENTITY_HEADER_LABEL) not in accepted.column_keys()
    assert all(normalize_header(label) not in APP_OWNED_HEADER_ALIASES for label in accepted.columns)


def test_a_header_that_merely_resembles_one_is_still_allowed() -> None:
    accepted = CategoryCreate(name=A_CATEGORY_NAME, columns=["Order", "Title", "Rows"])

    assert accepted.column_keys() == ["order", "title", "rows"]
