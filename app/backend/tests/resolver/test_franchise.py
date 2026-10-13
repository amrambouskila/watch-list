"""Franchise-prefix expansion: the templates are data under backend/data/, never literals in the module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tv_watchlist.resolver import franchise
from tv_watchlist.resolver.franchise import FRANCHISE_PREFIXES_PATH, franchise_candidates, franchise_templates

TITLE_PLACEHOLDER = "{title}"


def test_candidates_lead_with_the_bare_title_then_the_templates() -> None:
    assert franchise_candidates("one-piece", "One_Piece", "Dead End Adventure") == (
        "Dead End Adventure",
        "One Piece: Dead End Adventure",
    )


@pytest.mark.parametrize(
    ("slug", "name", "title", "expected"),
    [
        ("marvel", "Marvel", "The Consultant", "Marvel One-Shot: The Consultant"),
        ("star-wars", "Star_Wars", "Attack of the Clones", "Star Wars: Attack of the Clones"),
        ("naruto", "Naruto", "Ninja Clash in the Land of Snow", "Naruto the Movie: Ninja Clash in the Land of Snow"),
    ],
)
def test_the_probes_measured_cases_are_offered(slug: str, name: str, title: str, expected: str) -> None:
    assert expected in franchise_candidates(slug, name, title)


def test_an_unknown_slug_falls_back_to_the_generic_template() -> None:
    assert franchise_candidates("misc-tv", "Misc_TV", "Foo") == ("Foo", "Misc TV: Foo")


def test_the_bare_title_always_comes_first_and_candidates_are_unique() -> None:
    candidates = franchise_candidates("marvel", "Marvel", "The Consultant")
    assert candidates[0] == "The Consultant"
    assert len(candidates) == len(set(candidates))


def test_templates_come_from_the_data_file_not_the_module() -> None:
    source = Path(franchise.__file__).read_text(encoding="utf-8")
    assert TITLE_PLACEHOLDER not in source
    loaded = json.loads(FRANCHISE_PREFIXES_PATH.read_text(encoding="utf-8"))
    assert loaded
    assert all(
        isinstance(templates, list) and templates and all(TITLE_PLACEHOLDER in template for template in templates)
        for templates in loaded.values()
    )


def test_a_fixture_file_steers_the_loader(tmp_path: Path) -> None:
    path = tmp_path / "franchise_prefixes.json"
    path.write_text(json.dumps({"acme": [f"ACME Presents: {TITLE_PLACEHOLDER}"]}), encoding="utf-8")
    assert franchise_templates(path) == {"acme": ("ACME Presents: {title}",)}


@pytest.mark.parametrize(
    "payload",
    [
        {"acme": ["no placeholder at all"]},
        {"acme": [f"{TITLE_PLACEHOLDER} and {{extra}}"]},
        {"acme": ["{0}"]},
        {"acme": ["{title"]},
        {"acme": [f"{{title.__class__}} {TITLE_PLACEHOLDER}"]},
        {"acme": []},
        {"acme": "ACME Presents: {title}"},
        ["one-piece"],
    ],
)
def test_a_malformed_seed_file_is_refused_loudly(tmp_path: Path, payload: object) -> None:
    path = tmp_path / "franchise_prefixes.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="franchise_prefixes.json"):
        franchise_templates(path)


def test_a_missing_seed_file_says_which_path_it_wanted(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        franchise_templates(tmp_path / "absent.json")
