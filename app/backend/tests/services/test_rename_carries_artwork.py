"""Renaming a category must not orphan its card artwork."""

from __future__ import annotations

from pathlib import Path

from tv_watchlist.config import Settings
from tv_watchlist.models.category_rename import CategoryRename
from tv_watchlist.services.catalog import Catalog
from tv_watchlist.workbook.naming import slugify
from workbook_facts import WorkbookFacts

RENAMED_STEM = "Renamed_Under_A_New_Banner"
RENAMED = slugify(RENAMED_STEM)
HERO_SUFFIX = ".png"
ARTWORK = b"\x89PNG\r\n\x1a\nstand-in"
OTHER_ARTWORK = b"\x89PNG\r\n\x1a\nsomething-else"


def _artwork(heroes_dir: Path, name: str, body: bytes = ARTWORK) -> Path:
    heroes_dir.mkdir(parents=True, exist_ok=True)
    image = heroes_dir / name
    image.write_bytes(body)
    return image


async def _rename(catalog: Catalog, category_id: str, stem: str) -> None:
    mtime = (await catalog.detail(category_id)).mtime
    await catalog.rename_category(category_id, CategoryRename(stem=stem, expected_mtime=mtime))


async def test_renaming_a_category_takes_its_artwork_with_it(
    catalog: Catalog, settings: Settings, subject: WorkbookFacts
) -> None:
    _artwork(settings.heroes_dir, f"{subject.category_id}{HERO_SUFFIX}")

    await _rename(catalog, subject.category_id, RENAMED_STEM)

    assert (settings.heroes_dir / f"{RENAMED}{HERO_SUFFIX}").read_bytes() == ARTWORK
    assert not (settings.heroes_dir / f"{subject.category_id}{HERO_SUFFIX}").exists()


async def test_the_renamed_category_is_served_its_artwork(
    catalog: Catalog, settings: Settings, subject: WorkbookFacts
) -> None:
    _artwork(settings.heroes_dir, f"{subject.category_id}{HERO_SUFFIX}")

    await _rename(catalog, subject.category_id, RENAMED_STEM)

    assert (await catalog.detail(RENAMED)).hero_url is not None


async def test_renaming_a_category_that_has_no_artwork_is_harmless(
    catalog: Catalog, settings: Settings, subject: WorkbookFacts
) -> None:
    await _rename(catalog, subject.category_id, RENAMED_STEM)

    assert (await catalog.detail(RENAMED)).hero_url is None


async def test_artwork_stranded_under_the_new_name_is_retired_rather_than_overwritten(
    catalog: Catalog, settings: Settings, subject: WorkbookFacts
) -> None:
    _artwork(settings.heroes_dir, f"{subject.category_id}{HERO_SUFFIX}")
    _artwork(settings.heroes_dir, f"{RENAMED}{HERO_SUFFIX}", OTHER_ARTWORK)

    await _rename(catalog, subject.category_id, RENAMED_STEM)

    assert (settings.heroes_dir / f"{RENAMED}{HERO_SUFFIX}").read_bytes() == ARTWORK
    retired = list(settings.backup_dir.glob(f"{RENAMED}__*{HERO_SUFFIX}"))
    assert [path.read_bytes() for path in retired] == [OTHER_ARTWORK]
