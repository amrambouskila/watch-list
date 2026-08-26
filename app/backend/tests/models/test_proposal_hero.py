"""The hero arm of a proposal: candidate artwork, each with a licence and the page it came from."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tv_watchlist.constants import (
    MAX_HERO_CANDIDATES,
    MAX_HERO_DESCRIPTION_LENGTH,
    MAX_HERO_LICENCE_LENGTH,
    MAX_HERO_SOURCE_FILE_LENGTH,
    MAX_HERO_URL_LENGTH,
)
from tv_watchlist.models.hero_candidate import HeroCandidate
from tv_watchlist.models.proposal import Proposal
from tv_watchlist.models.proposal_hero import ProposalHero

CATEGORY_ID = "a-category"
CANDIDATE = {
    "url": "https://upload.wikimedia.org/wikipedia/commons/6/6c/Series_Logo.png",
    "source_file": "Series Logo.png",
    "licence": "Public domain",
    "page": "https://commons.wikimedia.org/wiki/File:Series_Logo.png",
    "description": "The 1977 logotype in white on transparency.",
}


def a_candidate(**overrides: str) -> dict[str, str]:
    """One well-formed candidate, with whichever field the test is about replaced."""
    return {**CANDIDATE, **overrides}


def a_hero_body(count: int) -> dict[str, object]:
    """A hero proposal offering however many candidates the test wants."""
    return {
        "kind": "hero",
        "category_id": CATEGORY_ID,
        "candidates": [a_candidate(description=f"candidate {index}") for index in range(count)],
    }


def test_a_candidate_keeps_the_licence_and_page_it_was_given() -> None:
    candidate = HeroCandidate.model_validate(CANDIDATE)

    assert candidate.licence == "Public domain"
    assert candidate.page == CANDIDATE["page"]
    assert candidate.source_file == "Series Logo.png"


@pytest.mark.parametrize("field", ["url", "page"])
@pytest.mark.parametrize(
    "value",
    ["file:///C:/Windows/win.ini", "ftp://example.test/logo.png", "javascript:alert(1)", "data:image/svg+xml,<svg/>"],
)
def test_a_candidate_address_that_is_not_http_is_refused(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        HeroCandidate.model_validate(a_candidate(**{field: value}))


@pytest.mark.parametrize(
    ("field", "cap"),
    [
        ("url", MAX_HERO_URL_LENGTH),
        ("page", MAX_HERO_URL_LENGTH),
        ("source_file", MAX_HERO_SOURCE_FILE_LENGTH),
        ("licence", MAX_HERO_LICENCE_LENGTH),
        ("description", MAX_HERO_DESCRIPTION_LENGTH),
    ],
)
def test_every_candidate_field_is_length_capped(field: str, cap: int) -> None:
    overlong = CANDIDATE[field] + "x" * cap

    with pytest.raises(ValidationError, match="at most"):
        HeroCandidate.model_validate(a_candidate(**{field: overlong}))


def test_up_to_three_candidates_are_offered_so_the_user_picks_by_eye() -> None:
    body = ProposalHero.model_validate(a_hero_body(MAX_HERO_CANDIDATES))

    assert len(body.candidates) == MAX_HERO_CANDIDATES


def test_more_candidates_than_the_cap_are_refused() -> None:
    with pytest.raises(ValidationError, match="at most"):
        ProposalHero.model_validate(a_hero_body(MAX_HERO_CANDIDATES + 1))


def test_a_hero_proposal_offering_nothing_to_pick_is_refused() -> None:
    with pytest.raises(ValidationError, match="at least"):
        ProposalHero.model_validate(a_hero_body(0))


def test_a_hero_body_parses_into_the_hero_arm() -> None:
    proposal = Proposal.model_validate({"id": "p-3", "summary": "artwork for a category", "body": a_hero_body(2)})

    assert isinstance(proposal.body, ProposalHero)
    assert proposal.body.category_id == CATEGORY_ID
    assert proposal.body.candidates[0].url == CANDIDATE["url"]
