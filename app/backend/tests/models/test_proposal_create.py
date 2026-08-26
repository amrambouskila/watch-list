from __future__ import annotations

import pytest
from pydantic import ValidationError

from tv_watchlist.models.category_create import CategoryCreate
from tv_watchlist.models.proposal_create import ProposalCreate


def test_a_create_proposal_wraps_a_whole_category_request() -> None:
    body = ProposalCreate(
        kind="create",
        category=CategoryCreate(name="Wartime Chronological", columns=["Order", "Title"], rows=[{"title": "Dunkirk"}]),
    )
    assert body.kind == "create"
    assert body.category.rows == [{"title": "Dunkirk"}]


def test_a_create_body_tagged_with_another_kind_is_rejected() -> None:
    with pytest.raises(ValidationError, match="create"):
        ProposalCreate(kind="edit", category=CategoryCreate(name="Wartime"))


def test_a_bad_row_key_inside_the_category_fails_the_whole_proposal() -> None:
    with pytest.raises(ValidationError, match="runtime"):
        ProposalCreate.model_validate(
            {"kind": "create", "category": {"name": "Wartime", "columns": ["Title"], "rows": [{"runtime": "106"}]}}
        )


def test_a_category_carrying_only_seed_titles_is_not_a_proposal() -> None:
    with pytest.raises(ValidationError, match="rows"):
        ProposalCreate.model_validate(
            {"kind": "create", "category": {"name": "Wartime", "columns": ["Title"], "titles": ["Dunkirk"]}}
        )
