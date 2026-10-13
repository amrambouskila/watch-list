"""Real transaction gates keep provider numbering coherent across playback evidence reads."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from statement_support import counted_statements
from tv_watchlist.constants import EPISODE_ORDER_LOCK_NAMESPACE
from tv_watchlist.data.episode_order_lock import try_episode_order_locks


@pytest.mark.parametrize("shared", [False, True])
async def test_empty_title_set_needs_no_transaction_or_query(engine: AsyncEngine, shared: bool) -> None:
    async with AsyncSession(engine) as session:
        with counted_statements(engine) as statements:
            assert await try_episode_order_locks(session, [], shared=shared)
            assert not session.in_transaction()
    assert statements == []


@pytest.mark.parametrize(
    ("holder_shared", "contender_shared"), [(True, True), (True, False), (False, True), (False, False)]
)
async def test_shared_and_exclusive_contention_is_nonblocking(
    engine: AsyncEngine, holder_shared: bool, contender_shared: bool
) -> None:
    title_id = uuid.uuid4()
    async with AsyncSession(engine) as holder, AsyncSession(engine) as contender:
        assert await try_episode_order_locks(holder, [title_id], shared=holder_shared)
        async with asyncio.timeout(1):
            acquired = await try_episode_order_locks(contender, [title_id], shared=contender_shared)
        assert acquired is (holder_shared and contender_shared)
        assert holder.in_transaction()
        assert contender.in_transaction()


@pytest.mark.parametrize("shared", [False, True])
@pytest.mark.parametrize("commit", [False, True])
async def test_caller_commit_or_rollback_releases_every_lock(engine: AsyncEngine, shared: bool, commit: bool) -> None:
    title_ids = [uuid.uuid4(), uuid.uuid4()]
    async with AsyncSession(engine) as holder, AsyncSession(engine) as contender:
        assert await try_episode_order_locks(holder, title_ids, shared=shared)
        assert not await try_episode_order_locks(contender, title_ids, shared=False)
        if commit:
            await holder.commit()
        else:
            await holder.rollback()
        assert await try_episode_order_locks(contender, title_ids, shared=False)


@pytest.mark.parametrize(
    ("first_shared", "second_shared"), [(True, True), (True, False), (False, True), (False, False)]
)
async def test_same_transaction_can_reacquire_or_upgrade_its_locks(
    engine: AsyncEngine, first_shared: bool, second_shared: bool
) -> None:
    title_id = uuid.uuid4()
    async with AsyncSession(engine) as session:
        assert await try_episode_order_locks(session, [title_id], shared=first_shared)
        assert await try_episode_order_locks(session, [title_id], shared=second_shared)


@pytest.mark.parametrize("shared", [False, True])
async def test_exclusive_lock_does_not_block_an_unrelated_title(engine: AsyncEngine, shared: bool) -> None:
    async with AsyncSession(engine) as holder, AsyncSession(engine) as contender:
        assert await try_episode_order_locks(holder, [uuid.uuid4()], shared=False)
        assert await try_episode_order_locks(contender, [uuid.uuid4()], shared=shared)


async def test_batch_uses_one_bound_statement_and_deduplicates_title_ids(engine: AsyncEngine) -> None:
    title_ids = [uuid.uuid4() for _ in range(100)]
    async with AsyncSession(engine) as session:
        with counted_statements(engine) as statements:
            assert await try_episode_order_locks(session, [*title_ids, *reversed(title_ids)], shared=True)
        assert len(statements) == 1
        assert "pg_try_advisory_xact_lock_shared" in statements[0]
        assert all(str(title_id) not in statements[0] for title_id in title_ids)
        count = await session.scalar(
            text(
                "SELECT count(*) FROM pg_locks WHERE pid = pg_backend_pid() AND locktype = 'advisory' "
                "AND classid = :namespace AND objsubid = 2"
            ),
            {"namespace": EPISODE_ORDER_LOCK_NAMESPACE},
        )
        assert count == len(title_ids)


async def test_failed_batch_retains_partial_locks_until_caller_rolls_back(engine: AsyncEngine) -> None:
    busy_title, free_title = uuid.uuid4(), uuid.uuid4()
    async with AsyncSession(engine) as holder, AsyncSession(engine) as batch, AsyncSession(engine) as probe:
        assert await try_episode_order_locks(holder, [busy_title], shared=False)
        assert not await try_episode_order_locks(batch, [busy_title, free_title], shared=True)
        assert not await try_episode_order_locks(probe, [free_title], shared=False)
        await batch.rollback()
        assert await try_episode_order_locks(probe, [free_title], shared=False)
        assert not await try_episode_order_locks(probe, [busy_title], shared=False)


async def test_key_is_postgres_hashtext_of_canonical_uuid_in_the_dedicated_namespace(engine: AsyncEngine) -> None:
    title_id = uuid.UUID("A42F6AE1-5EF5-45C7-A5CF-A78981E61B57")
    async with AsyncSession(engine) as holder, AsyncSession(engine) as contender:
        assert await try_episode_order_locks(holder, [title_id], shared=True)
        assert not await contender.scalar(
            text("SELECT pg_try_advisory_xact_lock(:namespace, hashtext(:title_id))"),
            {"namespace": EPISODE_ORDER_LOCK_NAMESPACE, "title_id": str(title_id)},
        )
        assert await contender.scalar(
            text("SELECT pg_try_advisory_xact_lock(:namespace, hashtext(:title_id))"),
            {"namespace": EPISODE_ORDER_LOCK_NAMESPACE + 1, "title_id": str(title_id)},
        )


async def test_two_key_namespace_does_not_conflict_with_same_bits_in_bigint_keyspace(engine: AsyncEngine) -> None:
    title_id = uuid.uuid4()
    async with AsyncSession(engine) as holder, AsyncSession(engine) as contender:
        assert await try_episode_order_locks(holder, [title_id], shared=False)
        assert await contender.scalar(
            text(
                "SELECT pg_try_advisory_xact_lock("
                "(CAST(:namespace AS bigint) << 32) | (CAST(hashtext(:title_id) AS bigint) & 4294967295))"
            ),
            {"namespace": EPISODE_ORDER_LOCK_NAMESPACE, "title_id": str(title_id)},
        )
