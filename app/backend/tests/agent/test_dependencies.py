"""The process-wide agent runtime, sharing the catalog the REST endpoints already use."""

from __future__ import annotations

from tv_watchlist.agent.dependencies import get_agent_runtime
from tv_watchlist.api.dependencies import get_catalog


def test_the_runtime_is_a_process_wide_singleton() -> None:
    assert get_agent_runtime() is get_agent_runtime()


def test_it_reuses_the_shared_catalog_rather_than_building_a_second_one() -> None:
    assert get_agent_runtime().catalog is get_catalog()
