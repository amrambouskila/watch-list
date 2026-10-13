"""The harness's own gates: when a missing Postgres skips, when it fails, and what may be rebuilt.

Most of this runs with no Postgres on the machine: the probe is monkeypatched, because the subject is
the gate's decision, not the database behind it. Those are sync - `require_reachable_postgres` calls
`asyncio.run`, which raises inside a running loop. The last two are the exception and take the real
database, because what the sweep does to a live run's database cannot be asserted against a mock.
"""

from __future__ import annotations

import asyncio
import os
from typing import Final

import asyncpg
import pytest

import database_support
from database_support import (
    DATABASE_VARIABLE,
    DEFAULT_TEST_DATABASE,
    DISPOSABLE_SUFFIX,
    REQUIRE_VARIABLE,
    _connect_to_maintenance,
    _process_is_alive,
    database_name,
    reclaim_abandoned_databases,
    require_disposable_database,
    require_reachable_postgres,
    settings_for_tests,
)
from tv_watchlist.config import Settings

ANOTHER_RUNNERS_PID: Final[int] = 4242
A_SWEEP_PROBE_STEM: Final[str] = "tv_sweep_probe_"
_PID_CEILING: Final[int] = 2**31 - 1


def _a_pid_no_process_can_have() -> int:
    """A pid that cannot exist, and a different one in every process.

    pid_t is a signed 32-bit int and no kernel allocates anywhere near its maximum - Linux caps pid_max
    at 4194304 and macOS at 99998 - so subtracting a real pid from the ceiling still lands far above
    anything allocatable. Derived from our own pid rather than fixed, because two local runners would
    otherwise race to create the one abandoned database this file's sweep test builds.
    """
    return _PID_CEILING - os.getpid()


async def _probe_fails(_settings: Settings) -> None:
    raise OSError("Connect call failed ('127.0.0.1', 5525)")


async def _probe_succeeds(_settings: Settings) -> None:
    return None


def test_the_database_name_is_read_at_call_time_not_at_import(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolving it at import would freeze the name before a fixture or a targeted run could set it."""
    monkeypatch.setenv(DATABASE_VARIABLE, "tv_other_test")
    assert database_name() == f"tv_other_p{os.getpid()}_test"
    assert settings_for_tests().postgres_db == f"tv_other_p{os.getpid()}_test"


def test_the_database_name_falls_back_to_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(DATABASE_VARIABLE, raising=False)
    stem = DEFAULT_TEST_DATABASE.removesuffix(DISPOSABLE_SUFFIX)
    assert database_name() == f"{stem}_p{os.getpid()}_test"


def test_two_runs_on_one_machine_never_share_a_test_database(monkeypatch: pytest.MonkeyPatch) -> None:
    """The session start DROPs what it migrates, so one shared name is one run killing the other."""
    mine = database_name()
    monkeypatch.setattr(database_support.os, "getpid", lambda: ANOTHER_RUNNERS_PID)
    theirs = database_name()

    assert theirs != mine
    assert theirs.endswith(DISPOSABLE_SUFFIX), "the guard checks the suffix, so the pid goes before it"
    assert require_disposable_database(theirs) is None


def test_a_configured_database_that_is_not_disposable_is_refused_before_the_pid_is_folded_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`TV_POSTGRES_DB=tv` stays a loud error, never a silent rewrite into a `tv_p<pid>_test`."""
    monkeypatch.setenv(DATABASE_VARIABLE, "tv")
    with pytest.raises(RuntimeError, match="disposable test database"):
        database_name()


def test_a_pid_that_is_running_is_alive_and_one_that_cannot_exist_is_not() -> None:
    """Signal 0 asks the kernel and sends nothing; the sweep reclaims only what answers no."""
    assert _process_is_alive(os.getpid()) is True
    assert _process_is_alive(_a_pid_no_process_can_have()) is False


def test_an_unreachable_postgres_skips_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(REQUIRE_VARIABLE, raising=False)
    monkeypatch.setattr(database_support, "_probe", _probe_fails)
    with pytest.raises(pytest.skip.Exception) as skipped:
        require_reachable_postgres()
    assert "no Postgres reachable" in str(skipped.value)


def test_an_unreachable_postgres_fails_when_the_environment_demands_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """CI sets TV_REQUIRE_POSTGRES: a broken service container must go red, never quietly green."""
    monkeypatch.setenv(REQUIRE_VARIABLE, "1")
    monkeypatch.setattr(database_support, "_probe", _probe_fails)
    with pytest.raises(pytest.fail.Exception) as failed:
        require_reachable_postgres()
    assert "no Postgres reachable" in str(failed.value)


def test_a_reachable_postgres_neither_skips_nor_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(REQUIRE_VARIABLE, "1")
    monkeypatch.setattr(database_support, "_probe", _probe_succeeds)
    assert require_reachable_postgres() is None


@pytest.mark.parametrize("name", ["tv_test", "tv_other_test"])
def test_a_test_database_may_be_rebuilt(name: str) -> None:
    assert require_disposable_database(name) is None


@pytest.mark.parametrize("name", ["tv", "postgres", "tv_testing"])
def test_the_owners_own_database_is_never_dropped(name: str) -> None:
    """migrated_database_url DROPs before it migrates; `tv` holds the owner's real Phase 1 projection."""
    with pytest.raises(RuntimeError, match="disposable test database"):
        require_disposable_database(name)


# -- the sweep, against the real Postgres -------------------------------------------------------------


async def _maintenance_call(sql: str, *arguments: object) -> list[asyncpg.Record]:
    connection = await _connect_to_maintenance(settings_for_tests())
    try:
        return list(await connection.fetch(sql, *arguments))
    finally:
        await connection.close()


def _exists(name: str) -> bool:
    return asyncio.run(_maintenance_call("SELECT 1 FROM pg_database WHERE datname = $1", name)) != []


def _create(name: str) -> None:
    # The name is built from this module's own constants, never from input, and CREATE DATABASE takes
    # no bind parameters.
    asyncio.run(_maintenance_call(f'CREATE DATABASE "{name}"'))


def _drop(name: str) -> None:
    asyncio.run(_maintenance_call(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


def _named_for(pid: int) -> str:
    return database_name().replace(f"_p{os.getpid()}{DISPOSABLE_SUFFIX}", f"_p{pid}{DISPOSABLE_SUFFIX}")


def test_the_sweep_reclaims_the_database_of_a_run_that_was_killed(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Teardown hands a finished run's database back; only a killed one leaves its name behind.

    Given a stem of its own, because the sweep is by definition machine-wide: under the suite's own
    stem, a second local runner's sweep would reclaim this probe database out from under the assertion.
    """
    monkeypatch.setenv(DATABASE_VARIABLE, f"{A_SWEEP_PROBE_STEM}{os.getpid()}{DISPOSABLE_SUFFIX}")
    abandoned = _named_for(_a_pid_no_process_can_have())
    _create(abandoned)
    try:
        assert abandoned in reclaim_abandoned_databases()
        assert _exists(abandoned) is False
    finally:
        _drop(abandoned)


def test_the_sweep_leaves_a_live_runs_database_alone(database_url: str) -> None:
    """This suite's own database is named for a pid that is very much alive, and it must stay."""
    assert database_name() in database_url
    assert database_name() not in reclaim_abandoned_databases()
    assert _exists(database_name()) is True
