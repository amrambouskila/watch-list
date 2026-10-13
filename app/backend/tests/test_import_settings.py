"""The Phase 3.5 import-pipeline `Settings` fields (T60, ADR-015): qBittorrent and the staging scan."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from tv_watchlist.config import Settings

QBITTORRENT_VARIABLES = ("TV_QBITTORRENT_URL", "TV_QBITTORRENT_USER", "TV_QBITTORRENT_PASSWORD")
IMPORT_VARIABLES = ("TV_IMPORT_STAGING_DIR", "TV_MEDIA_ROOT", "TV_IMPORT_CONCURRENCY")
FIELD_NAMES = (
    "qbittorrent_url",
    "qbittorrent_user",
    "qbittorrent_password",
    "import_staging_dir",
    "media_root",
    "import_concurrency",
)


def test_the_six_field_names_derive_their_env_names_mechanically() -> None:
    prefix = Settings.model_config.get("env_prefix", "")
    names = {f"{prefix}{name.upper()}" for name in FIELD_NAMES}
    assert names == set(QBITTORRENT_VARIABLES) | set(IMPORT_VARIABLES)


def test_settings_boots_with_none_of_the_six_set(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (*QBITTORRENT_VARIABLES, *IMPORT_VARIABLES):
        monkeypatch.delenv(name, raising=False)
    settings = Settings(_env_file=None)
    assert settings.qbittorrent_url is None
    assert settings.qbittorrent_user is None
    assert settings.qbittorrent_password is None
    assert settings.import_staging_dir is None
    assert settings.media_root is None
    assert settings.import_concurrency == 2


def test_the_qbittorrent_password_is_a_secret_that_never_renders() -> None:
    settings = Settings(_env_file=None, qbittorrent_password=SecretStr("qbittorrent-secret-value"))
    assert isinstance(settings.qbittorrent_password, SecretStr)
    assert "qbittorrent-secret-value" not in repr(settings)
    assert "qbittorrent-secret-value" not in str(settings)
    assert "qbittorrent-secret-value" not in str(settings.model_dump())


@pytest.mark.parametrize("concurrency", [0, 9, -1])
def test_import_concurrency_rejects_values_outside_its_documented_range(concurrency: int) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, import_concurrency=concurrency)


@pytest.mark.parametrize("concurrency", [1, 2, 8])
def test_import_concurrency_accepts_its_documented_range(concurrency: int) -> None:
    assert Settings(_env_file=None, import_concurrency=concurrency).import_concurrency == concurrency


def test_import_staging_dir_and_media_root_accept_a_configured_path(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, import_staging_dir=tmp_path, media_root=tmp_path)
    assert settings.import_staging_dir == tmp_path
    assert settings.media_root == tmp_path


@pytest.mark.parametrize(
    "base_url",
    [
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "http://host.docker.internal:8080",
        "https://qbittorrent.lan:8080",
    ],
)
def test_a_configured_qbittorrent_url_may_be_http_because_it_is_a_server_the_owner_runs(base_url: str) -> None:
    assert Settings(_env_file=None, qbittorrent_url=base_url).qbittorrent_url == base_url


@pytest.mark.parametrize(
    "base_url",
    [
        "ftp://qbittorrent:8080",
        "file:///media",
        "qbittorrent:8080",
        "not a url at all",
        "http://user:pass@qbittorrent:8080",
    ],
)
def test_a_malformed_qbittorrent_url_fails_at_boot_naming_the_variable(base_url: str) -> None:
    """The client that would be pinned to it is built lazily, so without this the owner would first meet
    a typo hours later, on the first scan (CLAUDE.md section 10.3, B21)."""
    with pytest.raises(ValidationError) as raised:
        Settings(_env_file=None, qbittorrent_url=base_url)

    assert "TV_QBITTORRENT_URL" in str(raised.value)


def test_the_validator_checks_shape_only_never_whether_the_host_is_actually_local() -> None:
    """`assert_within_configured_base` is a self-consistency check on the string's own shape - http(s),
    no embedded credentials, a parseable host and port, no traversal - not a check that the host is
    loopback or LAN. A well-formed public origin is therefore not refused here; the client's own
    allowlist-of-one is what actually pins every call to whatever base was configured (CLAUDE.md
    section 10.3, B21). Nothing about qBittorrent's own reachability is asserted at boot."""
    settings = Settings(_env_file=None, qbittorrent_url="https://api.themoviedb.org")
    assert settings.qbittorrent_url == "https://api.themoviedb.org"


def test_the_boot_refusal_repeats_no_part_of_the_value_it_refused() -> None:
    with pytest.raises(ValidationError) as raised:
        Settings(_env_file=None, qbittorrent_url="http://user:hunter2@qbittorrent:8080")

    message = next(error["msg"] for error in raised.value.errors())
    assert "hunter2" not in message
    assert message.endswith("TV_QBITTORRENT_URL must be an http or https origin with no credentials in it")
