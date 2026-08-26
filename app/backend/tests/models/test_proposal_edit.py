from __future__ import annotations

import pytest
from pydantic import ValidationError

from tv_watchlist.constants import MAX_PROPOSAL_CHANGES
from tv_watchlist.models.proposal_edit import ProposalEdit

READ_MTIME = 1_700_000_000.5


def test_an_edit_proposal_names_a_category_and_its_changes() -> None:
    body = ProposalEdit(
        kind="edit",
        category_id="a-category",
        read_mtime=READ_MTIME,
        changes=[{"kind": "add", "cells": {"title": "Dunkirk"}, "reason": "missing from the sheet"}],
    )
    assert body.category_id == "a-category"
    assert body.changes[0].cells == {"title": "Dunkirk"}


def test_an_edit_body_tagged_with_another_kind_is_rejected() -> None:
    with pytest.raises(ValidationError, match="edit"):
        ProposalEdit(kind="create", category_id="a-category", read_mtime=READ_MTIME, changes=[])


def test_more_changes_than_the_batch_cap_are_rejected() -> None:
    too_many = [{"kind": "remove", "row": 2}] * (MAX_PROPOSAL_CHANGES + 1)
    with pytest.raises(ValidationError, match="at most"):
        ProposalEdit(kind="edit", category_id="a-category", read_mtime=READ_MTIME, changes=too_many)


def test_an_incoherent_change_fails_the_whole_edit_body() -> None:
    with pytest.raises(ValidationError, match="remove"):
        ProposalEdit.model_validate(
            {
                "kind": "edit",
                "category_id": "a-category",
                "read_mtime": READ_MTIME,
                "changes": [{"kind": "remove", "row": 4, "cells": {"title": "Dunkirk"}}],
            }
        )


def test_an_edit_carries_the_mtime_its_row_numbers_were_resolved_against() -> None:
    body = ProposalEdit(kind="edit", category_id="a-category", read_mtime=READ_MTIME, changes=[])

    assert body.read_mtime == READ_MTIME


def test_an_edit_body_with_no_read_mtime_is_rejected_because_there_is_nothing_to_guard_with() -> None:
    with pytest.raises(ValidationError, match="read_mtime"):
        ProposalEdit.model_validate({"kind": "edit", "category_id": "a-category", "changes": []})
