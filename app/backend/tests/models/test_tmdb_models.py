"""Every recorded TMDB shape: frozen, and deaf to fields this project never asked for.

`extra="ignore"` is the untrusted-boundary rule (CLAUDE.md section 10.3, B10). A provider may grow a key
overnight; nothing it grows may reach SQL, a template or the UI by riding along inside a model.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from typing import Final, get_args

import pytest
from pydantic import BaseModel, ValidationError

import tv_watchlist.models.tmdb as tmdb_models
from tv_watchlist.models.tmdb.tmdb_alternative_title import TmdbAlternativeTitle
from tv_watchlist.models.tmdb.tmdb_alternative_titles import TmdbAlternativeTitles
from tv_watchlist.models.tmdb.tmdb_change_key import TmdbChangeKey
from tv_watchlist.models.tmdb.tmdb_changes_page import TmdbChangesPage
from tv_watchlist.models.tmdb.tmdb_configuration import TmdbConfiguration
from tv_watchlist.models.tmdb.tmdb_episode import TmdbEpisode
from tv_watchlist.models.tmdb.tmdb_external_ids import TmdbExternalIds
from tv_watchlist.models.tmdb.tmdb_image_configuration import TmdbImageConfiguration
from tv_watchlist.models.tmdb.tmdb_movie import TmdbMovie
from tv_watchlist.models.tmdb.tmdb_payload import TmdbPayload
from tv_watchlist.models.tmdb.tmdb_search_hit import TmdbMediaType, TmdbSearchHit
from tv_watchlist.models.tmdb.tmdb_search_page import TmdbSearchPage
from tv_watchlist.models.tmdb.tmdb_season import TmdbSeason
from tv_watchlist.models.tmdb.tmdb_season_summary import TmdbSeasonSummary
from tv_watchlist.models.tmdb.tmdb_tv import TmdbTv

# The smallest body each shape accepts, so a test can add one unknown key to it and see what survives.
MINIMAL: Final[list[tuple[type[TmdbPayload], dict[str, object]]]] = [
    (TmdbPayload, {}),
    (TmdbSearchHit, {"id": 1}),
    (TmdbSearchPage, {}),
    (TmdbMovie, {"id": 1, "title": "Attack of the Clones"}),
    (TmdbSeasonSummary, {"id": 1, "season_number": 0}),
    (TmdbTv, {"id": 1, "name": "One Piece"}),
    (TmdbEpisode, {"id": 1, "episode_number": 62, "season_number": 2}),
    (TmdbSeason, {"id": 1, "season_number": 2}),
    (TmdbExternalIds, {}),
    (TmdbImageConfiguration, {}),
    (TmdbConfiguration, {}),
    (TmdbAlternativeTitle, {"iso_3166_1": "JP", "title": "ワンピース"}),
    (TmdbAlternativeTitles, {}),
    (TmdbChangeKey, {"key": "season"}),
    (TmdbChangesPage, {}),
]
AN_UNKNOWN_UPSTREAM_FIELD: Final[str] = "softcore_or_whatever_tmdb_adds_next"


def _ids() -> list[str]:
    return [model.__name__ for model, _ in MINIMAL]


def _declared_models() -> list[type[BaseModel]]:
    """Every Pydantic model declared under `models/tmdb/`, found by walking the package rather than a list."""
    found: list[type[BaseModel]] = []
    for module_info in pkgutil.iter_modules(tmdb_models.__path__):
        module = importlib.import_module(f"{tmdb_models.__name__}.{module_info.name}")
        for _, member in inspect.getmembers(module, inspect.isclass):
            if issubclass(member, BaseModel) and member.__module__ == module.__name__:
                found.append(member)
    return found


@pytest.mark.parametrize(("model", "body"), MINIMAL, ids=_ids())
def test_an_unknown_upstream_field_is_ignored_not_stored(model: type[TmdbPayload], body: dict[str, object]) -> None:
    parsed = model.model_validate(body | {AN_UNKNOWN_UPSTREAM_FIELD: {"nested": ["anything"]}})

    assert AN_UNKNOWN_UPSTREAM_FIELD not in parsed.model_dump()
    assert not hasattr(parsed, AN_UNKNOWN_UPSTREAM_FIELD)


@pytest.mark.parametrize(("model", "body"), MINIMAL, ids=_ids())
def test_every_recorded_shape_is_frozen(model: type[TmdbPayload], body: dict[str, object]) -> None:
    parsed = model.model_validate(body)

    assert model.model_config["frozen"] is True
    field = next(iter(model.model_fields), None)
    if field is None:
        return  # TmdbPayload itself declares no fields, so its config is the whole assertion.
    with pytest.raises(ValidationError):
        setattr(parsed, field, None)


@pytest.mark.parametrize(("model", "body"), MINIMAL, ids=_ids())
def test_an_ignored_field_changes_nothing_about_what_was_parsed(
    model: type[TmdbPayload], body: dict[str, object]
) -> None:
    assert model.model_config["extra"] == "ignore"
    assert model.model_validate(body | {AN_UNKNOWN_UPSTREAM_FIELD: 1}) == model.model_validate(body)


def test_every_model_under_models_tmdb_inherits_the_boundary_config() -> None:
    """The invariant, not the list: a new provider shape cannot forget `frozen` or `extra="ignore"`."""
    declared = _declared_models()

    assert len(declared) >= len(MINIMAL)
    assert {model.__name__ for model, _ in MINIMAL} == {model.__name__ for model in declared}
    assert all(issubclass(model, TmdbPayload) for model in declared)


def test_the_provider_media_type_is_the_providers_vocabulary_not_the_schemas() -> None:
    """`clients/` may not import `data/`; the two vocabularies meet at the T19 ingest boundary."""
    assert set(get_args(TmdbMediaType)) == {"movie", "tv"}
    assert TmdbSearchHit.model_validate({"id": 1, "media_type": "tv"}).media_type == "tv"
    with pytest.raises(ValidationError):
        TmdbSearchHit.model_validate({"id": 1, "media_type": "series"})


def test_alternative_titles_read_both_the_tv_and_the_movie_shape() -> None:
    """`/tv/{id}` answers under `results` and `/movie/{id}` under `titles`; one model reads both."""
    entry = {"iso_3166_1": "JP", "title": "ワンピース", "type": ""}

    from_tv = TmdbAlternativeTitles.model_validate({"id": 37854, "results": [entry]})
    from_movie = TmdbAlternativeTitles.model_validate({"id": 1894, "titles": [entry]})

    assert from_tv.results == from_movie.results
    assert from_tv.results[0].title == "ワンピース"
    assert "titles" not in from_tv.model_dump()


def test_a_sequence_field_is_a_tuple_so_a_parsed_shape_cannot_be_mutated_in_place() -> None:
    series = TmdbTv.model_validate({"id": 1, "name": "One Piece", "seasons": [{"id": 2, "season_number": 0}]})

    assert isinstance(series.seasons, tuple)
    assert isinstance(TmdbSearchHit.model_validate({"id": 1, "genre_ids": [16, 12]}).genre_ids, tuple)


def test_an_episode_keeps_the_absolute_number_tmdb_gave_it() -> None:
    """One Piece season 2 episode 62. Nothing in the model layer renumbers it into a season-relative 1."""
    episode = TmdbEpisode.model_validate({"id": 1, "episode_number": 62, "season_number": 2, "runtime": 24})

    assert (episode.season_number, episode.episode_number) == (2, 62)
    # `runtime` is MINUTES, exactly as TMDB sent it; the ingest is the only place a duration becomes seconds.
    assert episode.runtime == 24


def test_a_changes_key_drops_the_polymorphic_items_it_sits_beside() -> None:
    """`items[].value` is a different shape per key, and nothing in this project may be typed `Any`."""
    parsed = TmdbChangeKey.model_validate({"key": "season", "items": [{"id": "x", "value": {"anything": 1}}]})

    assert parsed.key == "season"
    assert parsed.model_dump() == {"key": "season"}
