from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy import make_url

from env_example_support import env_example_entries
from tv_watchlist.config import REPO_ROOT, Settings, get_settings

# Documented for docker compose alone - these never become `Settings` fields.
COMPOSE_ONLY = frozenset({"TV_LIBRARY_HOST", "TV_JELLYFIN_PORT", "TV_JELLYFIN_MEDIA_HOST", "TV_IMPORT_STAGING_HOST"})
# The one Phase 3 name still ahead of its field: the availability client lands at T55, and until then
# `extra="ignore"` drops the variable. `TV_JELLYFIN_BASE_URL` and `TV_JELLYFIN_API_KEY` left this set at
# T48 - both are real `Settings` fields now, so the `fields` half of the check below covers them.
DEFERRED_TO_PHASE_THREE = frozenset({"TV_STREAMING_AVAILABILITY_API_KEY"})
PROVIDER_VARIABLES = ("TV_TMDB_READ_ACCESS_TOKEN", "TV_TVDB_API_KEY", "TV_TVDB_PIN")
POSTGRES_VARIABLES = (
    "TV_POSTGRES_HOST",
    "TV_POSTGRES_PORT",
    "TV_POSTGRES_DB",
    "TV_POSTGRES_USER",
    "TV_POSTGRES_PASSWORD",
)
# Awkward in every way a DSN can be broken: a space, and each character URL syntax gives a meaning to.
AN_AWKWARD_PASSWORD = "pa ss@/:%+"  # noqa: S105 - test input, not a credential; nothing authenticates with it


def test_the_env_file_is_the_repository_root_one_never_cwd_relative(declared_env_file: Path | None) -> None:
    assert declared_env_file == REPO_ROOT / ".env"
    assert REPO_ROOT == Path(__file__).resolve().parents[3]


def test_no_test_reaches_the_owners_root_env_file() -> None:
    """On the owner's machine that file exists and holds live credentials; the conftest fixture is why."""
    assert Settings.model_config["env_file"] is None
    settings = get_settings()
    assert settings.tmdb_read_access_token is None
    assert settings.tvdb_api_key is None
    assert settings.tvdb_pin is None


def test_database_url_round_trips_the_credential_and_renders_the_secret_only_there() -> None:
    settings = Settings(
        _env_file=None,
        postgres_host="db",
        postgres_port=5433,
        postgres_db="tv_test",
        postgres_user="t v",
        postgres_password=SecretStr(AN_AWKWARD_PASSWORD),
    )

    url = make_url(settings.database_url)

    assert url.drivername == "postgresql+asyncpg"
    assert url.username == "t v"
    assert url.password == AN_AWKWARD_PASSWORD
    assert (url.host, url.port, url.database) == ("db", 5433, "tv_test")
    assert AN_AWKWARD_PASSWORD not in repr(settings)
    assert AN_AWKWARD_PASSWORD not in str(settings.model_dump())


def test_defaults_point_at_the_compose_postgres_on_5525(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in POSTGRES_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    settings = Settings(_env_file=None)
    assert (settings.postgres_host, settings.postgres_port, settings.postgres_db, settings.postgres_user) == (
        "localhost",
        5525,
        "tv",
        "tv",
    )


def test_absent_provider_credentials_leave_the_app_bootable(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in PROVIDER_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    settings = Settings(_env_file=None)
    assert settings.tmdb_read_access_token is None
    assert settings.tvdb_api_key is None
    assert settings.tvdb_pin is None


def test_secrets_never_render_in_repr() -> None:
    settings = Settings(_env_file=None, tmdb_read_access_token=SecretStr("tmdb-secret-value"))
    assert "tmdb-secret-value" not in repr(settings)
    assert "tmdb-secret-value" not in str(settings.model_dump())


def test_every_env_example_variable_is_a_settings_field_or_deliberately_not_one() -> None:
    fields = {f"TV_{name.upper()}" for name in Settings.model_fields}
    known = COMPOSE_ONLY | DEFERRED_TO_PHASE_THREE | fields
    for name in env_example_entries():
        assert name in known, f"{name} is in .env.example but Settings has no field for it"


def test_an_absent_jellyfin_base_url_is_the_disabled_feature_rather_than_an_error() -> None:
    settings = Settings(_env_file=None)
    assert (settings.jellyfin_base_url, settings.jellyfin_api_key) == (None, None)


@pytest.mark.parametrize(
    "base_url",
    ["http://localhost:8096", "http://jellyfin:8096", "http://192.168.1.20:8096", "https://media.lan:8920"],
)
def test_a_configured_jellyfin_base_url_may_be_http_because_it_is_a_server_the_owner_runs(base_url: str) -> None:
    assert Settings(_env_file=None, jellyfin_base_url=base_url).jellyfin_base_url == base_url


@pytest.mark.parametrize(
    "base_url",
    ["ftp://jellyfin:8096", "file:///media", "jellyfin:8096", "not a url at all", "http://user:pass@jellyfin:8096"],
)
def test_a_malformed_jellyfin_base_url_fails_at_boot_naming_the_variable(base_url: str) -> None:
    """The client that would be pinned to it is built lazily, so without this the owner would first meet a
    typo hours later as a 503 (CLAUDE.md section 10.3, B16)."""
    with pytest.raises(ValidationError) as raised:
        Settings(_env_file=None, jellyfin_base_url=base_url)

    assert "TV_JELLYFIN_BASE_URL" in str(raised.value)


def test_the_boot_refusal_repeats_no_part_of_the_value_it_refused() -> None:
    """A base somebody typed a password into is exactly the one this refuses, so the sentence names none
    of it. Pydantic's own envelope still echoes the input it was given; that is the owner's own console,
    and the API key is a separate `SecretStr` field that never appears here."""
    with pytest.raises(ValidationError) as raised:
        Settings(_env_file=None, jellyfin_base_url="http://user:hunter2@jellyfin:8096")

    message = next(error["msg"] for error in raised.value.errors())
    assert "hunter2" not in message
    assert message.endswith("TV_JELLYFIN_BASE_URL must be an http or https origin with no credentials in it")


def test_the_jellyfin_key_is_a_secret_that_never_renders() -> None:
    settings = Settings(_env_file=None, jellyfin_api_key=SecretStr("jellyfin-secret-value"))
    assert "jellyfin-secret-value" not in repr(settings)
    assert "jellyfin-secret-value" not in str(settings.model_dump())
