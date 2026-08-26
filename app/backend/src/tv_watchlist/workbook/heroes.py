"""Optional per-category hero images the owner drops into the heroes folder."""

from __future__ import annotations

from pathlib import Path

from tv_watchlist.constants import HERO_SUFFIXES


def hero_files(heroes_dir: Path, category_id: str) -> list[Path]:
    """Every image filed under this category, in the order the app prefers them."""
    candidates = (heroes_dir / f"{category_id}{suffix}" for suffix in HERO_SUFFIXES)
    return [candidate for candidate in candidates if candidate.is_file()]


def hero_file(heroes_dir: Path, category_id: str) -> Path | None:
    """The image a card paints for this category, if one has been dropped in."""
    return next(iter(hero_files(heroes_dir, category_id)), None)


def move_heroes(heroes_dir: Path, old_id: str, new_id: str) -> None:
    """Carry a category's artwork to its new id, so a rename cannot orphan the card image."""
    for standing in hero_files(heroes_dir, old_id):
        standing.replace(heroes_dir / f"{new_id}{standing.suffix}")


def artwork_key(heroes_dir: Path, category_id: str) -> Path:
    """What one category's artwork is serialised on: the whole set of its images, not any one suffix."""
    return heroes_dir / category_id
