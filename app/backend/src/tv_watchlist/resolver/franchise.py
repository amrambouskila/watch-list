"""Franchise-prefix expansion, from templates kept as data under backend/data/ rather than in code."""

from __future__ import annotations

import json
from collections.abc import Mapping
from functools import cache
from pathlib import Path
from string import Formatter
from types import MappingProxyType
from typing import Final

# The workbook strips the franchise the catalogue keeps - "Dead End Adventure" is TMDB's "One Piece:
# Dead End Adventure" - and the probe measured that as ~17% of pairs. Adding a template is a data
# edit; the templates live beside the app's other parameter data, never as literals in this module.
FRANCHISE_PREFIXES_PATH: Final[Path] = Path(__file__).resolve().parents[3] / "data" / "franchise_prefixes.json"

# The one field a template may interpolate. Anything else - a second field, a positional slot, or an
# attribute reach such as `{title.__class__}` - is refused when the file loads rather than at match time.
TITLE_FIELD: Final[str] = "title"
FRANCHISE_WORD_SEPARATOR: Final[str] = "_"
GENERIC_TEMPLATE_JOINER: Final[str] = ": "


@cache
def franchise_templates(path: Path) -> Mapping[str, tuple[str, ...]]:
    """The prefix templates by category slug, read once per path and validated on the way in."""
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"{path} must hold an object keyed by category slug")
    return MappingProxyType({slug: _validated(slug, templates, path) for slug, templates in loaded.items()})


def franchise_candidates(category_slug: str, category_name: str, title: str) -> tuple[str, ...]:
    """The bare title, then this category's templates, then the generic prefix; deduplicated, order kept."""
    franchise = category_name.replace(FRANCHISE_WORD_SEPARATOR, " ").strip()
    # Concatenated rather than interpolated: no template literal belongs in this module, and the
    # test that keeps the templates in the data file reads this source to prove it.
    generic = (franchise + GENERIC_TEMPLATE_JOINER + title) if franchise else title
    # The path is passed rather than defaulted, so the seed caches under one key and is read once.
    templates = franchise_templates(FRANCHISE_PREFIXES_PATH).get(category_slug, ())
    expanded = (template.format(**{TITLE_FIELD: title}) for template in templates)
    return tuple(dict.fromkeys([title, *expanded, generic]))


def _validated(slug: str, templates: object, path: Path) -> tuple[str, ...]:
    if not isinstance(templates, list) or not templates:
        raise ValueError(f"{path}: {slug} must hold a non-empty list of templates")
    for template in templates:
        if not isinstance(template, str) or _fields_of(template, path) != {TITLE_FIELD}:
            raise ValueError(f"{path}: {slug} template {template!r} must interpolate {TITLE_FIELD} and nothing else")
    return tuple(templates)


def _fields_of(template: str, path: Path) -> set[str]:
    try:
        return {field for _, field, _, _ in Formatter().parse(template) if field is not None}
    except ValueError as error:
        raise ValueError(f"{path}: template {template!r} is not a valid format string") from error
