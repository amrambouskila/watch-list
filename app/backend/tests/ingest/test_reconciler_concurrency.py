from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import httpx
import pytest
from mirror_support import category_row, entries_for
from pydantic import SecretStr
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from provider_fixtures import A_RECORDED_KEY, A_RECORDED_PIN, TMDB, fixture_response
from review_support import ONE_PIECE_TMDB_ID, seeded_title, tmdb_runtime
from tv_watchlist.config import Settings
from tv_watchlist.data.enums import ResolutionState
from tv_watchlist.data.episode_order_lock import try_episode_order_locks
from tv_watchlist.data.models import Category, CuratedEntry, Title
from tv_watchlist.ingest.reconciler import Reconciler
from tv_watchlist.ingest.workbook_digest import digest_grid
from tv_watchlist.models.row_write import RowWrite
from tv_watchlist.services.catalog import Catalog
from tv_watchlist.services.locked_curated_entry import locked_curated_entry
from tv_watchlist.workbook.curated_columns import curated_columns
from tv_watchlist.workbook.reader import read_category


async def test_reconcile_waits_before_planning_and_refreshes_cached_rows_without_rewriting_a_digest_noop(
    engine: AsyncEngine, catalog: Catalog, subject_path: Path
) -> None:
    detail = read_category(subject_path)
    async with AsyncSession(engine, expire_on_commit=False) as seed:
        category = category_row(detail, uuid.uuid4())
        entries = entries_for(category.id, len(detail.rows), path=subject_path)
        seed.add_all([category, *entries])
        await seed.flush()
        written = await catalog.write_row_ids(
            detail.id,
            {entry.sheet_row: str(entry.id) for entry in entries if entry.sheet_row is not None},
            detail.mtime,
        )
        category.workbook_mtime = written.mtime
        await seed.commit()
    untouched_bytes = subject_path.read_bytes()
    untouched_stamp = subject_path.stat().st_mtime_ns
    try:
        async with AsyncSession(engine) as owner, AsyncSession(engine, expire_on_commit=False) as planning:
            held_category = await planning.get(Category, category.id)
            held_entry = await planning.get(CuratedEntry, entries[0].id)
            assert held_category is not None and held_category.workbook_digest is None
            assert held_entry is not None and held_entry.resolution_state is ResolutionState.UNRESOLVED
            locked_entry, locked_category = await locked_curated_entry(owner, entries[0].id)
            locked_category.workbook_digest = digest_grid(written.columns, written.rows)
            locked_entry.resolution_state = ResolutionState.CONFIRMED
            locked_entry.resolution_note = "Human decision while the next pass waited"
            await owner.flush()
            reconciler = Reconciler(planning, catalog, resolver=None, tmdb_ingest=None, order_ingest=None)
            waiting = asyncio.create_task(reconciler.reconcile(category.slug))
            try:
                with pytest.raises(TimeoutError):
                    await asyncio.wait_for(asyncio.shield(waiting), timeout=0.1)
                await owner.commit()
                result = await asyncio.wait_for(waiting, timeout=2)
                assert result.skipped and not result.workbook_written
                assert held_entry.resolution_state is ResolutionState.CONFIRMED
                assert held_entry.resolution_note == "Human decision while the next pass waited"
                assert held_category.workbook_digest == digest_grid(written.columns, written.rows)
                assert subject_path.read_bytes() == untouched_bytes
                assert subject_path.stat().st_mtime_ns == untouched_stamp
            finally:
                if not waiting.done():
                    waiting.cancel()
                await asyncio.gather(waiting, return_exceptions=True)
    finally:
        async with AsyncSession(engine) as cleanup:
            await cleanup.execute(delete(CuratedEntry).where(CuratedEntry.category_id == category.id))
            await cleanup.execute(delete(Category).where(Category.id == category.id))
            await cleanup.commit()


async def test_a_busy_numbering_rolls_back_prior_ingest_metadata_and_stamps_only_the_refusal(
    engine: AsyncEngine, settings: Settings, catalog: Catalog, subject_path: Path
) -> None:
    detail = read_category(subject_path)
    columns = curated_columns(detail.columns)
    assert columns.title is not None and columns.unit is not None and columns.release is not None
    changed = await catalog.update_row(
        detail.id,
        detail.rows[0].row,
        RowWrite(
            cells={columns.title.key: "One Piece", columns.unit.key: "E19–53", columns.release.key: "1999"},
            expected_mtime=detail.mtime,
        ),
    )
    before = subject_path.read_bytes()
    async with AsyncSession(engine, expire_on_commit=False) as seed:
        title = await seeded_title(seed, name="Before provider refresh", tmdb_id=ONE_PIECE_TMDB_ID)
        await seed.commit()
    configured = settings.model_copy(
        update={"tvdb_api_key": SecretStr(A_RECORDED_KEY), "tvdb_pin": SecretStr(A_RECORDED_PIN)}
    )
    runtime = tmdb_runtime(
        configured,
        catalog,
        engine,
        fixture_response(TMDB, "search_tv_one_piece"),
        fixture_response(TMDB, "tv_37854"),
        fixture_response(TMDB, "tv_37854_external_ids"),
        httpx.Response(404, json={}),
    )
    try:
        async with AsyncSession(engine) as playback, AsyncSession(engine) as ingest:
            assert await try_episode_order_locks(playback, [title.id], shared=True)
            result = await runtime.reconciler(ingest).reconcile(changed.id)
            assert result.refused is not None and "numbering is busy" in result.refused
            assert not result.workbook_written
        async with AsyncSession(engine) as check:
            assert await check.scalar(select(Title.name).where(Title.id == title.id)) == "Before provider refresh"
            category = await check.scalar(select(Category).where(Category.slug == changed.id))
            assert category is not None and category.last_ingest_error == result.refused
            assert category.last_ingested_at is None and category.workbook_digest is None
            assert (
                await check.scalar(
                    select(func.count()).select_from(CuratedEntry).where(CuratedEntry.category_id == category.id)
                )
                == 0
            )
            assert subject_path.read_bytes() == before
    finally:
        await runtime.aclose()
        async with AsyncSession(engine) as cleanup:
            await cleanup.execute(
                delete(CuratedEntry).where(
                    CuratedEntry.category_id.in_(select(Category.id).where(Category.slug == changed.id))
                )
            )
            await cleanup.execute(delete(Category).where(Category.slug == changed.id))
            await cleanup.execute(delete(Title).where(Title.id == title.id))
            await cleanup.commit()
