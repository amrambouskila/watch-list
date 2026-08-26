"""The always-on library context block: what is already tracked, and how each sheet is shaped."""

from __future__ import annotations

from library_choice import a_category_part_way_through
from tv_watchlist.agent.constants import DIGEST_STATUS_MARKERS
from tv_watchlist.agent.digest import build_library_digest
from tv_watchlist.constants import UNWATCHED, WATCHED, WORKBOOK_SUFFIX
from tv_watchlist.services.catalog import Catalog
from workbook_facts import WorkbookFacts


async def test_every_category_is_named_by_id_and_filename_stem(catalog: Catalog) -> None:
    digest = await build_library_digest(catalog)
    listing = await catalog.listing()

    for summary in listing.categories:
        assert summary.id in digest
        assert summary.name in digest
        assert summary.name == summary.file_name.removesuffix(WORKBOOK_SUFFIX)


async def test_a_categorys_column_keys_are_listed_so_rows_can_be_keyed_correctly(
    catalog: Catalog, subject: WorkbookFacts
) -> None:
    detail = await catalog.detail(subject.category_id)

    digest = await build_library_digest(catalog)

    for column in detail.columns:
        assert column.key in digest


async def test_every_title_in_the_library_is_present_so_duplicates_can_be_spotted(
    catalog: Catalog, subject: WorkbookFacts
) -> None:
    detail = await catalog.detail(subject.category_id)

    digest = await build_library_digest(catalog)

    for row in detail.rows:
        assert row.cells[subject.title_key] in digest


async def test_watched_and_unwatched_rows_carry_different_markers(catalog: Catalog) -> None:
    facts = a_category_part_way_through()
    detail = await catalog.detail(facts.category_id)
    watched = next(row for row in detail.rows if row.cells[facts.watch_key] == WATCHED)
    unwatched = next(row for row in detail.rows if row.cells[facts.watch_key] == UNWATCHED)

    digest = await build_library_digest(catalog)

    assert f"[{DIGEST_STATUS_MARKERS[WATCHED]}] {watched.cells[facts.title_key]}" in digest
    assert f"[{DIGEST_STATUS_MARKERS[UNWATCHED]}] {unwatched.cells[facts.title_key]}" in digest
