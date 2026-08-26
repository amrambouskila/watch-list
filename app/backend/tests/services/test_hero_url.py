"""A replaced hero has to reach the browser, not the copy it is already holding."""

from __future__ import annotations

import os
from pathlib import Path

from tv_watchlist.config import Settings
from tv_watchlist.services.catalog import Catalog
from workbook_facts import WorkbookFacts

FIRST_MTIME = 1_700_000_000
SECOND_MTIME = 1_700_000_900
HERO_SUFFIX = ".png"


def _artwork(heroes_dir: Path, category_id: str, body: bytes, mtime: int) -> Path:
    """Put an image where the card will look for it, stamped at a known time."""
    heroes_dir.mkdir(parents=True, exist_ok=True)
    image = heroes_dir / f"{category_id}{HERO_SUFFIX}"
    image.write_bytes(body)
    os.utime(image, (mtime, mtime))
    return image


async def test_a_category_with_no_artwork_still_has_no_url(catalog: Catalog, subject: WorkbookFacts) -> None:
    assert (await catalog.detail(subject.category_id)).hero_url is None


async def test_the_url_names_the_image_file_itself(
    catalog: Catalog, settings: Settings, subject: WorkbookFacts
) -> None:
    _artwork(settings.heroes_dir, subject.category_id, b"art", FIRST_MTIME)

    url = (await catalog.detail(subject.category_id)).hero_url

    assert url is not None
    assert url.split("?")[0] == f"/heroes/{subject.category_id}{HERO_SUFFIX}"


async def test_replacing_the_artwork_changes_the_url_the_card_asks_for(
    catalog: Catalog, settings: Settings, subject: WorkbookFacts
) -> None:
    _artwork(settings.heroes_dir, subject.category_id, b"first", FIRST_MTIME)
    before = (await catalog.detail(subject.category_id)).hero_url

    _artwork(settings.heroes_dir, subject.category_id, b"second", SECOND_MTIME)
    after = (await catalog.detail(subject.category_id)).hero_url

    assert before != after
