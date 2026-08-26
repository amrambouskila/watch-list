"""Retiring a category moves its workbook and its artwork aside; it never unlinks either."""

from __future__ import annotations

from pathlib import Path

import pytest
from sample_images import GIF89, PNG

from library_choice import another_category
from retirement_files import retirements, stamp_of
from tv_watchlist.config import Settings
from tv_watchlist.constants import WORKBOOK_SUFFIX
from tv_watchlist.services import retirement
from tv_watchlist.services.catalog import Catalog
from tv_watchlist.workbook.errors import CategoryNotFoundError, StaleWorkbookError, WorkbookLockedError
from tv_watchlist.workbook.locking import excel_lock_path
from workbook_facts import WorkbookFacts

HERO_SUFFIX = ".png"
A_SECOND_HERO_SUFFIX = ".gif"
UNKNOWN_ID = "no-category-answers-to-this"
# strftime returns text holding no % directive verbatim, so both retirements in a test land on
# one stamp: the same-second collision, made deterministic instead of raced for.
ONE_SECOND = "one-second"
# Far enough from any real mtime that no filesystem granularity could make it look current.
A_STAMP_THE_WORKBOOK_NEVER_HAD = 1_000_000.0


def artwork_for(settings: Settings, category_id: str) -> Path:
    """A stand-in hero image filed under a category id."""
    settings.heroes_dir.mkdir(parents=True, exist_ok=True)
    image = settings.heroes_dir / f"{category_id}{HERO_SUFFIX}"
    image.write_bytes(PNG)
    return image


async def retire(catalog: Catalog, category_id: str) -> None:
    """Retire a category at whatever stamp it currently carries."""
    mtime = (await catalog.detail(category_id)).mtime
    await catalog.retire_category(category_id, mtime)


async def test_the_workbook_and_its_artwork_move_together_under_one_stamp(
    catalog: Catalog, settings: Settings, subject: WorkbookFacts, subject_path: Path
) -> None:
    original = subject_path.read_bytes()
    artwork_for(settings, subject.category_id)

    await retire(catalog, subject.category_id)

    retired_workbook = retirements(settings.backup_dir, subject.stem, WORKBOOK_SUFFIX)
    retired_artwork = retirements(settings.backup_dir, subject.category_id, HERO_SUFFIX)
    assert [path.read_bytes() for path in retired_workbook] == [original]
    assert [path.read_bytes() for path in retired_artwork] == [PNG]
    assert stamp_of(retired_workbook[0], subject.stem) == stamp_of(retired_artwork[0], subject.category_id)
    assert not subject_path.exists()
    assert not (settings.heroes_dir / f"{subject.category_id}{HERO_SUFFIX}").exists()


async def test_a_category_with_no_artwork_retires_on_its_own(
    catalog: Catalog, settings: Settings, subject: WorkbookFacts, subject_path: Path
) -> None:
    original = subject_path.read_bytes()

    await retire(catalog, subject.category_id)

    retired = retirements(settings.backup_dir, subject.stem, WORKBOOK_SUFFIX)
    assert [path.read_bytes() for path in retired] == [original]
    assert not subject_path.exists()


async def test_a_workbook_open_in_excel_is_refused_and_nothing_moves(
    catalog: Catalog, settings: Settings, subject: WorkbookFacts, subject_path: Path
) -> None:
    artwork = artwork_for(settings, subject.category_id)
    mtime = (await catalog.detail(subject.category_id)).mtime
    excel_lock_path(subject_path).write_bytes(b"owner")

    with pytest.raises(WorkbookLockedError):
        await catalog.retire_category(subject.category_id, mtime)

    assert subject_path.is_file()
    assert artwork.is_file()
    assert retirements(settings.backup_dir, subject.stem, WORKBOOK_SUFFIX) == []
    assert retirements(settings.backup_dir, subject.category_id, HERO_SUFFIX) == []


async def test_a_stale_stamp_is_refused_and_nothing_moves(
    catalog: Catalog, settings: Settings, subject: WorkbookFacts, subject_path: Path
) -> None:
    artwork = artwork_for(settings, subject.category_id)

    with pytest.raises(StaleWorkbookError):
        await catalog.retire_category(subject.category_id, A_STAMP_THE_WORKBOOK_NEVER_HAD)

    assert subject_path.is_file()
    assert artwork.is_file()
    assert retirements(settings.backup_dir, subject.stem, WORKBOOK_SUFFIX) == []
    assert retirements(settings.backup_dir, subject.category_id, HERO_SUFFIX) == []


async def test_an_unknown_category_is_refused(catalog: Catalog, settings: Settings) -> None:
    with pytest.raises(CategoryNotFoundError):
        await catalog.retire_category(UNKNOWN_ID, A_STAMP_THE_WORKBOOK_NEVER_HAD)

    assert not settings.backup_dir.is_dir()


async def test_a_second_retirement_of_the_same_name_does_not_overwrite_the_first(
    catalog: Catalog,
    settings: Settings,
    subject: WorkbookFacts,
    subject_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The stamp is only accurate to the second, so both retirements want the very same filename."""
    monkeypatch.setattr(retirement, "BACKUP_TIMESTAMP_FORMAT", ONE_SECOND)
    original = subject_path.read_bytes()
    successor = another_category().copied_into(settings.library_dir).read_bytes()
    artwork_for(settings, subject.category_id)

    await retire(catalog, subject.category_id)
    subject_path.write_bytes(successor)
    (settings.heroes_dir / f"{subject.category_id}{HERO_SUFFIX}").write_bytes(GIF89)
    await retire(catalog, subject.category_id)

    kept = [path.read_bytes() for path in retirements(settings.backup_dir, subject.stem, WORKBOOK_SUFFIX)]
    images = [path.read_bytes() for path in retirements(settings.backup_dir, subject.category_id, HERO_SUFFIX)]
    assert sorted(kept) == sorted([original, successor])
    assert sorted(images) == sorted([PNG, GIF89])


async def test_the_listing_no_longer_holds_the_retired_category_and_the_files_are_still_on_disk(
    catalog: Catalog, settings: Settings, subject: WorkbookFacts, subject_path: Path
) -> None:
    artwork_for(settings, subject.category_id)
    before = await catalog.listing()
    mtime = (await catalog.detail(subject.category_id)).mtime

    listing = await catalog.retire_category(subject.category_id, mtime)

    assert subject.category_id in {category.id for category in before.categories}
    assert subject.category_id not in {category.id for category in listing.categories}
    assert listing.unreadable == []
    assert len(listing.categories) == len(before.categories) - 1
    assert len(retirements(settings.backup_dir, subject.stem, WORKBOOK_SUFFIX)) == 1
    assert len(retirements(settings.backup_dir, subject.category_id, HERO_SUFFIX)) == 1


async def test_every_image_a_category_holds_is_carried_out_with_it(
    catalog: Catalog, settings: Settings, subject: WorkbookFacts, subject_path: Path
) -> None:
    """A card paints only the first suffix, but a second one left behind would be inherited."""
    artwork_for(settings, subject.category_id)
    spare = settings.heroes_dir / f"{subject.category_id}{A_SECOND_HERO_SUFFIX}"
    spare.write_bytes(GIF89)

    await retire(catalog, subject.category_id)

    assert list(settings.heroes_dir.iterdir()) == []
    kept = retirements(settings.backup_dir, subject.category_id, A_SECOND_HERO_SUFFIX)
    assert [path.read_bytes() for path in kept] == [GIF89]


async def test_a_namesake_created_afterwards_inherits_none_of_the_retired_artwork(
    catalog: Catalog, settings: Settings, subject: WorkbookFacts, subject_path: Path
) -> None:
    """The id is derived from the filename, so the next category to take it must start bare."""
    artwork_for(settings, subject.category_id)
    (settings.heroes_dir / f"{subject.category_id}{A_SECOND_HERO_SUFFIX}").write_bytes(GIF89)
    successor = subject_path.read_bytes()
    await retire(catalog, subject.category_id)

    subject_path.write_bytes(successor)

    assert (await catalog.detail(subject.category_id)).hero_url is None
