"""Two files deriving one id: the app reaches only one, and says plainly which one it cannot."""

from __future__ import annotations

import shutil
from pathlib import Path

from library_choice import the_category_a_new_name_could_shadow
from tv_watchlist.constants import WORKBOOK_SUFFIX
from tv_watchlist.services.catalog import Catalog
from tv_watchlist.workbook import discovery
from tv_watchlist.workbook.naming import workbook_filename
from workbook_facts import WorkbookFacts

NOT_A_WORKBOOK = b"dropped in through Explorer, and not a workbook at all"


def a_pair_sharing_one_id(library: Path) -> tuple[WorkbookFacts, Path]:
    """A category, plus a second file the filesystem keeps apart but the app cannot tell from it."""
    facts = the_category_a_new_name_could_shadow()
    dropped_in = library / workbook_filename(facts.shadowing_name)
    shutil.copy2(facts.copied_into(library), dropped_in)
    return facts, dropped_in


def the_other(library: Path, facts: WorkbookFacts, dropped_in: Path) -> str:
    """Whichever of the pair the app does not answer to that id with."""
    answering = discovery.resolve(library, facts.category_id).name
    return next(name for name in (facts.file_name, dropped_in.name) if name != answering)


async def test_only_one_card_carries_an_id_that_two_files_derive(catalog: Catalog, library: Path) -> None:
    facts, _ = a_pair_sharing_one_id(library)

    listing = await catalog.listing()

    assert len([item for item in listing.categories if item.id == facts.category_id]) == 1


async def test_the_file_the_app_cannot_reach_is_reported_rather_than_vanishing(catalog: Catalog, library: Path) -> None:
    facts, dropped_in = a_pair_sharing_one_id(library)

    listing = await catalog.listing()

    assert [item.file_name for item in listing.shadowed] == [the_other(library, facts, dropped_in)]


async def test_the_report_names_the_file_that_did_answer_to_the_shared_id(catalog: Catalog, library: Path) -> None:
    facts, _ = a_pair_sharing_one_id(library)

    listing = await catalog.listing()

    assert [item.answered_by for item in listing.shadowed] == [discovery.resolve(library, facts.category_id).name]


async def test_the_report_names_the_id_the_two_files_share(catalog: Catalog, library: Path) -> None:
    facts, _ = a_pair_sharing_one_id(library)

    listing = await catalog.listing()

    assert [item.category_id for item in listing.shadowed] == [facts.category_id]


async def test_a_library_holding_no_such_pair_reports_nothing_shadowed(catalog: Catalog) -> None:
    listing = await catalog.listing()

    assert listing.shadowed == []


async def test_every_file_in_the_library_is_either_shown_or_accounted_for(catalog: Catalog, library: Path) -> None:
    a_pair_sharing_one_id(library)

    listing = await catalog.listing()

    accounted = (
        {item.file_name for item in listing.categories}
        | {item.file_name for item in listing.unreadable}
        | {item.file_name for item in listing.shadowed}
    )
    assert accounted == {path.name for path in library.glob(f"*{WORKBOOK_SUFFIX}")}


async def test_a_file_that_cannot_be_opened_still_hides_the_namesake_it_shadows(
    catalog: Catalog, library: Path
) -> None:
    """Which of the pair answers is decided by name alone, so the test corrupts whichever one that is."""
    facts, dropped_in = a_pair_sharing_one_id(library)
    # Picking the dropped-in file instead would only be the answering one for some spellings of the
    # owner's filenames, and this is a property of resolution order, not of what anything is called.
    answering = discovery.resolve(library, facts.category_id)
    answering.write_bytes(NOT_A_WORKBOOK)

    listing = await catalog.listing()

    assert [item.file_name for item in listing.shadowed] == [the_other(library, facts, dropped_in)]
    assert facts.category_id not in {item.id for item in listing.categories}
    assert [item.file_name for item in listing.unreadable] == [answering.name]


async def test_the_shadowed_file_is_left_untouched_on_disk(catalog: Catalog, library: Path) -> None:
    facts, dropped_in = a_pair_sharing_one_id(library)
    before = {path.name: path.read_bytes() for path in library.glob(f"*{WORKBOOK_SUFFIX}")}

    await catalog.listing()

    assert {path.name: path.read_bytes() for path in library.glob(f"*{WORKBOOK_SUFFIX}")} == before
    assert dropped_in.is_file()
