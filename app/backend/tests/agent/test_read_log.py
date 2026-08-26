"""What each category was read at, so a proposal can be guarded against the file it was resolved on."""

from __future__ import annotations

from tv_watchlist.agent.read_log import ReadLog

CATEGORY = "a-category"
OTHER_CATEGORY = "a-different-category"
MTIME = 1_700_000_000.5
LATER_MTIME = 1_700_000_600.25


def test_a_category_this_session_never_read_has_no_stamp_to_guard_with() -> None:
    assert ReadLog().mtime_of(CATEGORY) is None


def test_a_recorded_read_comes_back_as_the_mtime_it_was_read_at() -> None:
    log = ReadLog()

    log.record(CATEGORY, MTIME)

    assert log.mtime_of(CATEGORY) == MTIME


def test_reading_the_same_category_again_replaces_the_earlier_stamp() -> None:
    log = ReadLog()

    log.record(CATEGORY, MTIME)
    log.record(CATEGORY, LATER_MTIME)

    assert log.mtime_of(CATEGORY) == LATER_MTIME


def test_each_category_is_stamped_independently_of_the_others() -> None:
    log = ReadLog()

    log.record(CATEGORY, MTIME)
    log.record(OTHER_CATEGORY, LATER_MTIME)

    assert log.mtime_of(CATEGORY) == MTIME
    assert log.mtime_of(OTHER_CATEGORY) == LATER_MTIME


def test_forgetting_a_category_leaves_it_with_no_stamp_to_guard_with() -> None:
    log = ReadLog()
    log.record(CATEGORY, MTIME)

    log.forget(CATEGORY)

    assert log.mtime_of(CATEGORY) is None


def test_forgetting_a_category_this_session_never_read_is_harmless() -> None:
    log = ReadLog()

    log.forget(CATEGORY)

    assert log.mtime_of(CATEGORY) is None


def test_forgetting_one_category_leaves_every_other_stamp_alone() -> None:
    log = ReadLog()
    log.record(CATEGORY, MTIME)
    log.record(OTHER_CATEGORY, LATER_MTIME)

    log.forget(CATEGORY)

    assert log.mtime_of(OTHER_CATEGORY) == LATER_MTIME
