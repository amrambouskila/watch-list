"""Every recorded TheTVDB shape: frozen, and deaf to fields this project never asked for.

`extra="ignore"` is the untrusted-boundary rule (CLAUDE.md section 10.3, B10). A provider may grow a key
overnight; nothing it grows may reach SQL, a template or the UI by riding along inside a model.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from typing import Final

import pytest
from pydantic import BaseModel, SecretStr, ValidationError

import tv_watchlist.models.tvdb as tvdb_models
from tv_watchlist.models.tvdb.tvdb_episode import TvdbEpisode
from tv_watchlist.models.tvdb.tvdb_episode_page import TvdbEpisodePage
from tv_watchlist.models.tvdb.tvdb_episodes_result import TvdbEpisodesResult
from tv_watchlist.models.tvdb.tvdb_login import TvdbLogin
from tv_watchlist.models.tvdb.tvdb_payload import TvdbPayload
from tv_watchlist.models.tvdb.tvdb_season_type import TvdbSeasonType
from tv_watchlist.models.tvdb.tvdb_translation import TvdbTranslation
from tv_watchlist.models.tvdb.tvdb_update import TvdbUpdate
from tv_watchlist.models.tvdb.tvdb_update_page import TvdbUpdatePage

# The smallest body each shape accepts, so a test can add one unknown key to it and see what survives.
MINIMAL: Final[list[tuple[type[TvdbPayload], dict[str, object]]]] = [
    (TvdbPayload, {}),
    (TvdbLogin, {"data": {"token": "recorded-token"}}),
    (TvdbSeasonType, {"id": 1, "type": "an-ordering-this-test-made-up"}),
    (TvdbEpisode, {"id": 361887}),
    (TvdbEpisodePage, {}),
    (TvdbEpisodesResult, {}),
    (TvdbTranslation, {}),
    (TvdbUpdate, {}),
    (TvdbUpdatePage, {}),
]
AN_UNKNOWN_UPSTREAM_FIELD: Final[str] = "companyOrWhateverTheTvdbAddsNext"


def _ids() -> list[str]:
    return [model.__name__ for model, _ in MINIMAL]


def _declared_models() -> list[type[BaseModel]]:
    """Every Pydantic model declared under `models/tvdb/`, found by walking the package rather than a list."""
    found: list[type[BaseModel]] = []
    for module_info in pkgutil.iter_modules(tvdb_models.__path__):
        module = importlib.import_module(f"{tvdb_models.__name__}.{module_info.name}")
        for _, member in inspect.getmembers(module, inspect.isclass):
            if issubclass(member, BaseModel) and member.__module__ == module.__name__:
                found.append(member)
    return found


@pytest.mark.parametrize(("model", "body"), MINIMAL, ids=_ids())
def test_an_unknown_upstream_field_is_ignored_not_stored(model: type[TvdbPayload], body: dict[str, object]) -> None:
    parsed = model.model_validate(body | {AN_UNKNOWN_UPSTREAM_FIELD: {"nested": ["anything"]}})

    assert AN_UNKNOWN_UPSTREAM_FIELD not in parsed.model_dump()
    assert not hasattr(parsed, AN_UNKNOWN_UPSTREAM_FIELD)


@pytest.mark.parametrize(("model", "body"), MINIMAL, ids=_ids())
def test_every_recorded_shape_is_frozen(model: type[TvdbPayload], body: dict[str, object]) -> None:
    parsed = model.model_validate(body)

    assert model.model_config["frozen"] is True
    field = next(iter(model.model_fields), None)
    if field is None:
        return  # TvdbPayload itself declares no fields, so its config is the whole assertion.
    with pytest.raises(ValidationError):
        setattr(parsed, field, None)


@pytest.mark.parametrize(("model", "body"), MINIMAL, ids=_ids())
def test_an_ignored_field_changes_nothing_about_what_was_parsed(
    model: type[TvdbPayload], body: dict[str, object]
) -> None:
    assert model.model_config["extra"] == "ignore"
    assert model.model_validate(body | {AN_UNKNOWN_UPSTREAM_FIELD: 1}) == model.model_validate(body)


def test_every_model_under_models_tvdb_inherits_the_boundary_config() -> None:
    """The invariant, not the list: a new provider shape cannot forget `frozen` or `extra="ignore"`."""
    declared = _declared_models()

    assert len(declared) >= len(MINIMAL)
    assert {model.__name__ for model, _ in MINIMAL} == {model.__name__ for model in declared}
    assert all(issubclass(model, TvdbPayload) for model in declared)


def test_the_login_token_is_a_secret_that_does_not_render_itself() -> None:
    """A token that printed itself would land in every traceback that touched a login response."""
    login = TvdbLogin.model_validate({"status": "success", "data": {"token": "a-token"}})

    assert isinstance(login.token, SecretStr)
    assert "a-token" not in repr(login)
    assert login.token.get_secret_value() == "a-token"


def test_a_season_type_carries_whatever_name_the_service_sent() -> None:
    """A type this app has never seen is storable and ignorable, which is the whole point of reading the list."""
    parsed = TvdbSeasonType.model_validate(
        {"id": 99, "name": "Some Order", "type": "notatypeyet", "alternateName": None}
    )

    assert (parsed.id, parsed.type, parsed.name, parsed.alternate_name) == (99, "notatypeyet", "Some Order", None)


def test_an_episode_keeps_both_numberings_the_ordering_gave_it() -> None:
    """`number` is this ordering's number; `absolute_number` is the absolute one. Nothing here derives either."""
    episode = TvdbEpisode.model_validate(
        {"id": 1, "seriesId": 81797, "number": 1, "seasonNumber": 2, "absoluteNumber": 62, "runtime": 25}
    )

    assert (episode.season_number, episode.number, episode.absolute_number) == (2, 1, 62)
    # `runtime` is MINUTES, exactly as TheTVDB sent it; the ingest is the only place a duration becomes seconds.
    assert episode.runtime == 25


def test_a_page_reads_its_episodes_out_of_data_and_its_cursor_out_of_links() -> None:
    page = TvdbEpisodePage.model_validate(
        {
            "data": {"id": 81797, "episodes": [{"id": 1, "number": 1}]},
            "links": {"next": "https://api4.thetvdb.com/v4/x?page=1", "total_items": 1179, "page_size": 500},
        }
    )

    assert (page.total_items, page.page_size) == (1179, 500)
    assert page.next_url == "https://api4.thetvdb.com/v4/x?page=1"
    assert isinstance(page.episodes, tuple)


def test_a_page_with_no_episodes_array_parses_to_nothing_rather_than_failing() -> None:
    """An unrecognised season type answers 200 with an empty array; the page must be readable, not a crash."""
    page = TvdbEpisodePage.model_validate({"data": {"id": 81797, "episodes": []}, "links": {"next": None}})

    assert page.episodes == ()
    assert page.next_url is None


@pytest.mark.parametrize("episodes", [(), (TvdbEpisode.model_validate({"id": 1}),)])
def test_known_is_derived_from_the_episodes_and_cannot_be_asserted_by_a_caller(
    episodes: tuple[TvdbEpisode, ...],
) -> None:
    """`known` is a property, so no call site can claim an empty ordering is a known-empty one."""
    result = TvdbEpisodesResult(episodes=episodes, pages=1)

    assert result.known is bool(episodes)
    assert "known" not in TvdbEpisodesResult.model_fields


def test_a_result_reports_nothing_until_a_walk_says_what_the_service_claimed() -> None:
    """`None` is "the pages carried no count", which is not the same claim as "the ordering holds none"."""
    assert TvdbEpisodesResult().reported is None
    assert TvdbEpisodesResult(reported=934).reported == 934


def test_a_translation_reads_the_english_name_out_of_the_envelope() -> None:
    parsed = TvdbTranslation.model_validate({"data": {"name": "One Piece", "language": "eng", "aliases": ["x"]}})

    assert (parsed.name, parsed.language, parsed.aliases) == ("One Piece", "eng", ("x",))


def test_an_update_row_reads_the_camel_case_the_service_sends() -> None:
    parsed = TvdbUpdate.model_validate(
        {"recordId": 11916476, "recordType": "", "entityType": "episodes", "method": "update", "timeStamp": 1789913063}
    )

    assert (parsed.record_id, parsed.entity_type, parsed.method, parsed.time_stamp) == (
        11916476,
        "episodes",
        "update",
        1789913063,
    )


def test_a_sequence_field_is_a_tuple_so_a_parsed_shape_cannot_be_mutated_in_place() -> None:
    page = TvdbEpisodePage.model_validate({"data": {"episodes": [{"id": 1}, {"id": 2}]}})

    assert isinstance(page.episodes, tuple)
    assert isinstance(TvdbTranslation.model_validate({"data": {"aliases": ["a"]}}).aliases, tuple)


def test_an_update_page_reads_its_records_out_of_data_and_its_cursor_out_of_links() -> None:
    """A window that carries a `next` is a PARTIAL window, and only `links` can say so."""
    page = TvdbUpdatePage.model_validate(
        {
            "data": [{"recordId": 1, "entityType": "episodes"}],
            "links": {"next": "https://api4.thetvdb.com/v4/updates?page=1", "total_items": 900, "page_size": 500},
        }
    )

    assert (len(page.updates), page.total_items, page.page_size) == (1, 900, 500)
    assert page.next_url == "https://api4.thetvdb.com/v4/updates?page=1"
    assert TvdbUpdatePage.model_validate({"data": [], "links": {"next": None}}).next_url is None
