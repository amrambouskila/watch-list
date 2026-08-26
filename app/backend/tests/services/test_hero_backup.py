"""Moving a category's artwork aside: every image survives, even when two moves share a second."""

from __future__ import annotations

from pathlib import Path
from typing import Final

import pytest

from library_choice import a_category
from tv_watchlist.config import Settings
from tv_watchlist.services import hero_backup

# The module names artwork by category id alone, so any id the library really answers to is faithful.
CATEGORY: Final[str] = a_category().category_id
A_SUFFIX: Final[str] = ".png"
ANOTHER_SUFFIX: Final[str] = ".gif"
# strftime returns text holding no % directive verbatim, so every retirement in a test lands on one
# stamp: the same-second collision, made deterministic instead of raced for.
ONE_SECOND: Final[str] = "one-second"
FIRST_MARK: Final[bytes] = b"the hand-recoloured mark that cannot be made again"
SECOND_MARK: Final[bytes] = b"the mark that replaced it"
THIRD_MARK: Final[bytes] = b"and the one that replaced that"


@pytest.fixture(autouse=True)
def _one_second(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hero_backup, "BACKUP_TIMESTAMP_FORMAT", ONE_SECOND)


def standing(settings: Settings, data: bytes, suffix: str = A_SUFFIX) -> Path:
    """Artwork filed under the category, as a pick would leave it."""
    settings.heroes_dir.mkdir(parents=True, exist_ok=True)
    image = settings.heroes_dir / f"{CATEGORY}{suffix}"
    image.write_bytes(data)
    return image


def kept(settings: Settings) -> list[bytes]:
    """Every file the backups folder holds, by content."""
    if not settings.backup_dir.is_dir():
        return []
    return sorted(path.read_bytes() for path in settings.backup_dir.rglob("*") if path.is_file())


def retire(settings: Settings) -> None:
    hero_backup.retire_heroes(settings.heroes_dir, settings.backup_dir, CATEGORY)


def test_two_replacements_inside_one_second_both_keep_the_artwork_they_moved_aside(
    settings: Settings,
) -> None:
    standing(settings, FIRST_MARK)
    retire(settings)
    standing(settings, SECOND_MARK)

    retire(settings)

    assert kept(settings) == sorted([FIRST_MARK, SECOND_MARK])


def test_a_third_replacement_in_the_same_second_still_displaces_nothing(settings: Settings) -> None:
    for mark in (FIRST_MARK, SECOND_MARK, THIRD_MARK):
        standing(settings, mark)
        retire(settings)

    assert kept(settings) == sorted([FIRST_MARK, SECOND_MARK, THIRD_MARK])


def test_images_of_different_suffixes_moved_together_stay_apart(settings: Settings) -> None:
    standing(settings, FIRST_MARK, A_SUFFIX)
    standing(settings, SECOND_MARK, ANOTHER_SUFFIX)

    retire(settings)

    assert kept(settings) == sorted([FIRST_MARK, SECOND_MARK])


def test_the_category_is_left_holding_no_artwork_at_all(settings: Settings) -> None:
    standing(settings, FIRST_MARK, A_SUFFIX)
    standing(settings, SECOND_MARK, ANOTHER_SUFFIX)

    retire(settings)

    assert list(settings.heroes_dir.glob(f"{CATEGORY}.*")) == []


def test_a_category_holding_no_artwork_leaves_the_backups_folder_alone(settings: Settings) -> None:
    retire(settings)

    assert not settings.backup_dir.exists()


def test_every_kept_image_is_filed_under_the_category_and_keeps_its_own_suffix(settings: Settings) -> None:
    standing(settings, FIRST_MARK, A_SUFFIX)
    retire(settings)
    standing(settings, SECOND_MARK, A_SUFFIX)

    retire(settings)

    filed = sorted(path.name for path in settings.backup_dir.iterdir())
    assert len(filed) == 2
    assert all(name.startswith(f"{CATEGORY}__{ONE_SECOND}") and name.endswith(A_SUFFIX) for name in filed)
