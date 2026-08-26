"""Sessions live in memory, keyed by id, and are evicted once they have gone quiet."""

from __future__ import annotations

import httpx
import pytest
from mock_responder import MockResponder
from recording_reader import RecordingReader
from stub_client import StubClient

from tv_watchlist.agent.errors import UnknownProposalError, UnknownSessionError
from tv_watchlist.agent.fetcher import Fetcher
from tv_watchlist.agent.registry import SessionRegistry
from tv_watchlist.agent.session import ChatSession
from tv_watchlist.models.proposal import Proposal
from tv_watchlist.services.catalog import Catalog

IDLE_SECONDS = 100.0
READ_MTIME = 1_700_000_000.5
EDIT_CATEGORY = "a-category"
PROPOSAL = Proposal(
    id="p1",
    summary="91 wartime films",
    body={
        "kind": "edit",
        "category_id": EDIT_CATEGORY,
        "read_mtime": READ_MTIME,
        "changes": [],
    },
)


class Clock:
    """A hand-wound monotonic clock, so idle eviction is tested without sleeping."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def registry(catalog: Catalog, clock: Clock) -> SessionRegistry:
    def build(session_id: str) -> ChatSession:
        fetcher = Fetcher(RecordingReader(), transport=MockResponder(httpx.Response(200)).transport)
        return ChatSession(session_id, catalog, fetcher, client_factory=StubClient)

    return SessionRegistry(build, idle_seconds=IDLE_SECONDS, clock=clock)


def client_of(session: ChatSession) -> StubClient:
    client = session.client
    assert isinstance(client, StubClient)
    return client


async def test_creating_a_session_starts_it_and_gives_it_an_id(registry: SessionRegistry) -> None:
    session = await registry.create()

    assert session.id
    assert client_of(session).connected is True


async def test_two_sessions_do_not_share_an_id(registry: SessionRegistry) -> None:
    first = await registry.create()
    second = await registry.create()

    assert first.id != second.id


async def test_a_live_session_is_returned_by_id(registry: SessionRegistry) -> None:
    session = await registry.create()

    assert await registry.get(session.id) is session


async def test_an_unknown_id_is_refused(registry: SessionRegistry) -> None:
    with pytest.raises(UnknownSessionError):
        await registry.get("never-existed")


async def test_closing_a_session_disconnects_it_and_forgets_it(registry: SessionRegistry) -> None:
    session = await registry.create()

    await registry.close(session.id)

    assert client_of(session).connected is False
    with pytest.raises(UnknownSessionError):
        await registry.get(session.id)


async def test_closing_an_unknown_session_is_refused(registry: SessionRegistry) -> None:
    with pytest.raises(UnknownSessionError):
        await registry.close("never-existed")


async def test_a_session_left_idle_past_the_deadline_is_evicted_on_the_next_access(
    registry: SessionRegistry, clock: Clock
) -> None:
    session = await registry.create()

    clock.now += IDLE_SECONDS + 1
    with pytest.raises(UnknownSessionError):
        await registry.get(session.id)
    assert client_of(session).connected is False


async def test_using_a_session_resets_its_idle_clock(registry: SessionRegistry, clock: Clock) -> None:
    session = await registry.create()

    clock.now += IDLE_SECONDS - 1
    await registry.get(session.id)
    clock.now += IDLE_SECONDS - 1

    assert await registry.get(session.id) is session


async def test_eviction_of_one_session_leaves_a_fresher_one_alone(registry: SessionRegistry, clock: Clock) -> None:
    stale = await registry.create()
    clock.now += IDLE_SECONDS - 1
    fresh = await registry.create()

    clock.now += 2

    assert await registry.get(fresh.id) is fresh
    assert client_of(stale).connected is False


async def test_a_pending_proposal_is_found_by_id_across_sessions(registry: SessionRegistry) -> None:
    await registry.create()
    holder = await registry.create()
    await holder.record_proposal(PROPOSAL)

    assert registry.proposal(PROPOSAL.id) == PROPOSAL


async def test_an_unknown_proposal_id_is_refused(registry: SessionRegistry) -> None:
    await registry.create()

    with pytest.raises(UnknownProposalError):
        registry.proposal("no-such-proposal")


async def test_an_applied_proposal_is_cleared_from_the_session_holding_it(registry: SessionRegistry) -> None:
    holder = await registry.create()
    await holder.record_proposal(PROPOSAL)

    registry.applied(PROPOSAL.id)

    assert holder.pending_proposal is None
    with pytest.raises(UnknownProposalError):
        registry.proposal(PROPOSAL.id)


async def test_an_applied_edit_forgets_the_read_stamp_its_write_spent(registry: SessionRegistry) -> None:
    holder = await registry.create()
    holder.read_log.record(EDIT_CATEGORY, READ_MTIME)
    await holder.record_proposal(PROPOSAL)

    registry.applied(PROPOSAL.id)

    assert holder.read_log.mtime_of(EDIT_CATEGORY) is None


async def test_closing_the_registry_disconnects_every_session(registry: SessionRegistry) -> None:
    first = await registry.create()
    second = await registry.create()

    await registry.aclose()

    assert client_of(first).connected is False
    assert client_of(second).connected is False
    with pytest.raises(UnknownSessionError):
        await registry.get(first.id)
