"""The Jellyfin response models, driven by the hand-authored bodies in `tests/fixtures/jellyfin/`.

Those fixtures are NOT recordings - no Jellyfin has ever been reachable on this machine - and
`tests/fixtures/jellyfin/README.md` says which five things T49 still confirms against a live server. The
`ProviderIds` casing is the sharpest of them, which is why every assertion about it here is parametrized
over all three spellings the schema permits rather than pinned to the one the fixtures happen to use.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

import pytest
from pydantic import ValidationError

from provider_fixtures import JELLYFIN, fixture_json
from tv_watchlist.constants import (
    MAX_JELLYFIN_ID_LENGTH,
    MAX_JELLYFIN_NAME_LENGTH,
    MAX_JELLYFIN_PATH_LENGTH,
    TICKS_PER_SECOND,
)
from tv_watchlist.models.jellyfin.jellyfin_item_dto import JellyfinItemDto
from tv_watchlist.models.jellyfin.jellyfin_item_page import JellyfinItemPage
from tv_watchlist.models.jellyfin.jellyfin_provider_ids import JellyfinProviderIds

ONE_PIECE_TMDB_ID: Final[int] = 37854
IRON_MAN_TMDB_ID: Final[int] = 1726
# 2 h at .NET's 100 ns tick. Written out rather than computed from the divisor under test.
TWO_HOURS_OF_TICKS: Final[int] = 72_000_000_000
TWO_HOURS_OF_SECONDS: Final[int] = 7200
A_TWENTY_FOUR_MINUTE_EPISODE_IN_TICKS: Final[int] = 14_400_000_000


def _movies() -> JellyfinItemPage:
    return JellyfinItemPage.model_validate(fixture_json(JELLYFIN, "items_movies_page1"))


def _episodes() -> JellyfinItemPage:
    return JellyfinItemPage.model_validate(fixture_json(JELLYFIN, "shows_episodes_one_piece"))


# --- the page envelope ----------------------------------------------------------------------------------


def test_a_page_reads_items_total_and_start_index_by_their_pascal_case_names() -> None:
    page = _movies()

    assert (len(page.items), page.total_record_count, page.start_index) == (3, 3, 0)


def test_a_page_of_a_paged_walk_carries_the_start_index_it_was_asked_for() -> None:
    page = JellyfinItemPage.model_validate(fixture_json(JELLYFIN, "items_series_page2"))

    assert (page.start_index, page.total_record_count, len(page.items)) == (2, 3, 1)


def test_an_empty_page_is_a_valid_page_rather_than_a_failure() -> None:
    page = JellyfinItemPage.model_validate(fixture_json(JELLYFIN, "items_empty"))

    assert (page.items, page.total_record_count) == ((), 0)


def test_a_page_with_no_keys_at_all_defaults_rather_than_raising() -> None:
    """`BaseItemDtoQueryResult` marks nothing required, so every member has to survive being absent."""
    page = JellyfinItemPage.model_validate({})

    assert (page.items, page.total_record_count, page.start_index) == ((), 0, 0)


def test_a_page_ignores_a_key_the_schema_does_not_carry() -> None:
    page = JellyfinItemPage.model_validate({"Items": [], "TotalRecordCount": 0, "SomethingNew": {"a": 1}})

    assert page.model_extra in (None, {})


# --- one item -------------------------------------------------------------------------------------------


def test_the_string_caps_are_named_constants_rather_than_bare_numbers() -> None:
    fields = JellyfinItemDto.model_fields
    caps = {name: [m.max_length for m in fields[name].metadata if hasattr(m, "max_length")] for name in fields}

    assert caps["id"] == [MAX_JELLYFIN_ID_LENGTH]
    assert caps["series_id"] == [MAX_JELLYFIN_ID_LENGTH]
    assert caps["name"] == [MAX_JELLYFIN_NAME_LENGTH]
    assert caps["path"] == [MAX_JELLYFIN_PATH_LENGTH]


def test_an_item_reads_every_field_the_sync_stores() -> None:
    iron_man = _movies().items[0]

    assert iron_man.id == "0a1b2c3d4e5f6071829304a5b6c7d8e9"
    assert iron_man.name == "Iron Man"
    assert iron_man.kind == "Movie"
    assert iron_man.path is not None and iron_man.path.endswith(".mkv")
    assert iron_man.provider_ids.tmdb_id == IRON_MAN_TMDB_ID


def test_an_episode_carries_its_numbers_verbatim_and_never_reinterprets_them() -> None:
    """Whatever order the file naming produced is what these mean; the ordering is resolved elsewhere."""
    first, _, multi = _episodes().items

    assert (first.parent_index_number, first.index_number, first.index_number_end) == (1, 1, None)
    assert (multi.parent_index_number, multi.index_number, multi.index_number_end) == (1, 3, 4)
    assert multi.series_id == first.series_id


def test_an_item_ignores_a_field_the_client_never_asked_for() -> None:
    """`extra="ignore"` is the untrusted-boundary rule: nothing unrequested reaches SQL by accident."""
    item = JellyfinItemDto.model_validate(
        {"Id": "abc", "Name": "x", "Type": "Movie", "Overview": "<script>alert(1)</script>"}
    )

    assert item.model_extra in (None, {})


def test_an_item_without_an_id_is_refused_rather_than_stored_with_a_blank_one() -> None:
    """An id is the only thing the sync keys on, so its absence is a body this client cannot read."""
    with pytest.raises(ValidationError):
        JellyfinItemDto.model_validate({"Name": "x", "Type": "Movie"})


def test_a_null_name_becomes_the_empty_string_rather_than_failing_the_whole_page() -> None:
    """The schema marks `Name` nullable, so one nameless item must not cost a whole library scan."""
    item = JellyfinItemDto.model_validate({"Id": "abc", "Name": None, "Type": "Movie"})

    assert item.name == ""


def test_an_item_is_frozen() -> None:
    item = _movies().items[0]

    with pytest.raises(ValidationError):
        item.name = "something else"


# --- ticks become seconds exactly once ------------------------------------------------------------------


def test_run_time_ticks_become_whole_seconds_by_integer_division() -> None:
    item = JellyfinItemDto.model_validate(
        {"Id": "abc", "Name": "x", "Type": "Movie", "RunTimeTicks": TWO_HOURS_OF_TICKS}
    )

    assert item.run_time_seconds == TWO_HOURS_OF_SECONDS


def test_ticks_are_not_a_field_beside_the_seconds_they_became() -> None:
    """Two attributes for one duration is how a second, different conversion gets written downstream."""
    assert "run_time_ticks" not in JellyfinItemDto.model_fields
    assert not [name for name in JellyfinItemDto.model_fields if "tick" in name.lower()]


def test_the_divisor_is_the_one_constant_the_project_names() -> None:
    assert TICKS_PER_SECOND == 10_000_000


def test_a_fixture_episode_runtime_converts_to_the_minutes_the_file_actually_is() -> None:
    first = _episodes().items[0]

    assert A_TWENTY_FOUR_MINUTE_EPISODE_IN_TICKS // 10_000_000 == 24 * 60
    assert first.run_time_seconds == 24 * 60


def test_a_tick_count_that_is_not_a_whole_second_truncates_rather_than_rounding() -> None:
    """Integer division, once, at the boundary - never a float of seconds anywhere in the schema."""
    item = JellyfinItemDto.model_validate({"Id": "abc", "Name": "x", "Type": "Movie", "RunTimeTicks": 19_999_999})

    assert item.run_time_seconds == 1


def test_an_absent_runtime_stays_absent_rather_than_becoming_zero_seconds() -> None:
    item = JellyfinItemDto.model_validate({"Id": "abc", "Name": "x", "Type": "Movie"})

    assert item.run_time_seconds is None


def test_a_runtime_that_is_not_a_number_is_refused_rather_than_silently_converted() -> None:
    """The validator only divides an int, so anything else still meets the field's own type check."""
    with pytest.raises(ValidationError):
        JellyfinItemDto.model_validate({"Id": "abc", "Name": "x", "Type": "Movie", "RunTimeTicks": "lots"})


def test_a_negative_tick_count_is_refused() -> None:
    with pytest.raises(ValidationError):
        JellyfinItemDto.model_validate({"Id": "abc", "Name": "x", "Type": "Movie", "RunTimeTicks": -1})


# --- the provider-id map, whose key casing is unconfirmed until T49 --------------------------------------


@pytest.mark.parametrize("key", ["Tmdb", "TMDB", "tmdb"])
def test_provider_ids_are_read_through_one_explicit_key_whatever_its_casing(key: str) -> None:
    """`ProviderIds` is `additionalProperties: string` with no enum, so all three spellings are schema-valid."""
    ids = JellyfinProviderIds.model_validate({key: str(ONE_PIECE_TMDB_ID)})

    assert ids.tmdb_id == ONE_PIECE_TMDB_ID


@pytest.mark.parametrize("key", ["Tmdb", "TMDB", "tmdb"])
def test_an_item_reaches_its_tmdb_id_through_that_same_key(key: str) -> None:
    item = JellyfinItemDto.model_validate(
        {"Id": "abc", "Name": "One Piece", "Type": "Series", "ProviderIds": {key: str(ONE_PIECE_TMDB_ID)}}
    )

    assert item.provider_ids.tmdb_id == ONE_PIECE_TMDB_ID


def test_an_item_with_no_provider_ids_has_an_empty_map_rather_than_none() -> None:
    item = JellyfinItemDto.model_validate({"Id": "abc", "Name": "x", "Type": "Movie"})

    assert (item.provider_ids.root, item.provider_ids.tmdb_id) == ({}, None)


def test_a_null_provider_id_map_is_read_as_an_empty_one() -> None:
    """The schema marks `ProviderIds` nullable, and a null map is 'no ids', never a failure."""
    item = JellyfinItemDto.model_validate({"Id": "abc", "Name": "x", "Type": "Movie", "ProviderIds": None})

    assert item.provider_ids.tmdb_id is None


def test_an_item_with_other_providers_but_no_tmdb_id_reports_none() -> None:
    """Spider-Man is in the fixture with an IMDb id only, which is the `hasTmdbId=false` half of a library."""
    spider_man = _movies().items[2]

    assert spider_man.provider_ids.tmdb_id is None
    assert spider_man.provider_ids.root["Imdb"] == "tt0145487"


@pytest.mark.parametrize(
    "value",
    [
        "",
        "not-a-number",
        "1726x",
        # Every one of these is a value `int()` accepts and a TMDB id is not. `+1726` and ` 1726 ` are
        # the same id spelled two ways nobody wrote; `1_726` is a different number entirely; `-1` could
        # not be a row; and the last is past what an `integer` column holds, so it would fail the INSERT
        # halfway through a library scan rather than at this boundary.
        "+1726",
        " 1726 ",
        "1_726",
        "-1",
        "2147483648",
        "12345678901",
    ],
)
def test_a_tmdb_id_that_is_not_an_integer_is_read_as_absent_rather_than_reaching_sql(value: str) -> None:
    """A free-text map is a boundary: junk in it is 'no id', and it never becomes a `title.tmdb_id`."""
    assert JellyfinProviderIds.model_validate({"Tmdb": value}).tmdb_id is None


def test_a_null_value_under_the_tmdb_key_is_read_as_absent() -> None:
    assert JellyfinProviderIds.model_validate({"Tmdb": None}).tmdb_id is None


# --- the DateLastSaved ambiguity -------------------------------------------------------------------------


def test_date_last_saved_is_absent_from_every_body_the_schema_describes() -> None:
    """12.1's `BaseItemDto` declares 155 properties, sets `additionalProperties: false`, and `DateLastSaved`
    is not one of them - even though it IS a valid `ItemFields` value and `minDateLastSaved` IS a valid
    filter. The fixtures follow the schema; T49 confirms what a running server really sends."""
    assert all(item.date_last_saved is None for item in _movies().items)


def test_date_last_saved_is_still_read_when_a_server_does_send_it() -> None:
    page = JellyfinItemPage.model_validate(fixture_json(JELLYFIN, "items_movies_with_date_last_saved"))

    assert page.items[0].date_last_saved == datetime(2026, 9, 19, 21, 14, 7, 123456, tzinfo=UTC)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        # Which of the three ISO spellings 12.1 really sends is one of this fixture directory's open
        # questions, so all three are accepted and normalised here rather than downstream.
        ("2026-09-19T21:14:07Z", datetime(2026, 9, 19, 21, 14, 7, tzinfo=UTC)),
        ("2026-09-19T21:14:07+00:00", datetime(2026, 9, 19, 21, 14, 7, tzinfo=UTC)),
        ("2026-09-19T21:14:07", datetime(2026, 9, 19, 21, 14, 7, tzinfo=UTC)),
    ],
    ids=["zulu", "offset", "naive"],
)
def test_a_date_last_saved_without_an_offset_is_read_as_utc(value: str, expected: datetime) -> None:
    """`jellyfin_item.date_last_saved` is `timestamptz`, and asyncpg refuses a naive datetime for one.

    Left naive, an offsetless stamp would fail the INSERT partway through a scan instead of being settled
    at the boundary - and it would be wrong by exactly the machine's timezone if it ever did land.
    """
    item = JellyfinItemDto.model_validate({"Id": "abc", "Type": "Movie", "DateLastSaved": value})

    assert item.date_last_saved == expected
    assert item.date_last_saved is not None and item.date_last_saved.tzinfo is not None
