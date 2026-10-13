"""Runtime settings, all overridable through the environment."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

from tv_watchlist.clients.errors import OutboundUrlError
from tv_watchlist.clients.http_guard import assert_within_configured_base
from tv_watchlist.constants import BACKUP_DIRNAME, BACKUP_INTERVAL_SECONDS, BACKUP_RETENTION, HERO_DIRNAME

# The repository root - the one place a .env lives (CLAUDE.md section 8.3). An absolute path, never a
# cwd-relative string: the launchers start the backend from app/backend. Inside the image this resolves
# to /srv, where no .env exists, and compose passes the variables through `environment:` instead.
REPO_ROOT = Path(__file__).resolve().parents[4]
APP_DIR = REPO_ROOT / "app"


class Settings(BaseSettings):
    """Environment-driven configuration for the watch-order service."""

    model_config = SettingsConfigDict(env_prefix="TV_", env_file=REPO_ROOT / ".env", extra="ignore")

    library_dir: Path = Field(default=REPO_ROOT)
    backend_port: int = Field(default=8284, ge=1, le=65535)
    frontend_port: int = Field(default=5284, ge=1, le=65535)
    backup_dir: Path = Field(default=APP_DIR / BACKUP_DIRNAME)
    backup_retention: int = Field(default=BACKUP_RETENTION, ge=1)
    backup_interval_seconds: float = Field(default=BACKUP_INTERVAL_SECONDS, ge=0)
    heroes_dir: Path = Field(default=APP_DIR / HERO_DIRNAME)

    # Postgres - the Phase 1 projection. 5525 is the HOST publication; compose overrides host and port.
    postgres_host: str = "localhost"
    postgres_port: int = Field(default=5525, ge=1, le=65535)
    postgres_db: str = "tv"
    postgres_user: str = "tv"
    postgres_password: SecretStr = Field(default=SecretStr("tv"))

    # Provider credentials. `None` is a disabled feature, never a boot failure.
    tmdb_read_access_token: SecretStr | None = None
    tvdb_api_key: SecretStr | None = None
    tvdb_pin: SecretStr | None = None

    # Jellyfin - Phase 3. `None` is a disabled feature: every entry reports not_in_library and the
    # player never renders. Only the scheme, host and port are configuration; the paths are constants.
    jellyfin_base_url: str | None = None
    jellyfin_api_key: SecretStr | None = None

    @field_validator("jellyfin_base_url")
    @classmethod
    def _a_configured_base_must_be_one_the_guard_accepts(cls, value: str | None) -> str | None:
        """A malformed base fails at BOOT, naming the variable, rather than at the first playback.

        Absent is the disabled feature and stays valid. Present-but-unusable - not http(s), carrying
        credentials, unparseable - is a configuration error, and the client that would be pinned to it is
        built lazily, so without this the owner would first meet it hours later as a 503
        (CLAUDE.md section 10.3, B16). The message deliberately repeats no part of the value: a base
        somebody typed a password into is exactly the one this refuses.
        """
        if value is None:
            return None
        try:
            assert_within_configured_base(value, value)
        except OutboundUrlError as error:
            raise ValueError(
                "TV_JELLYFIN_BASE_URL must be an http or https origin with no credentials in it"
            ) from error
        return value

    # qBittorrent - Phase 3.5, the import pipeline (ADR-015). `None` is the disabled feature, exactly
    # like Jellyfin: the staging-folder scan runs without it, and only the completed-torrents arm needs
    # it. Read-only client, no add-torrent method (ADR-015) - see CLAUDE.md section 10.3, B21.
    qbittorrent_url: str | None = None
    qbittorrent_user: str | None = None
    qbittorrent_password: SecretStr | None = None

    @field_validator("qbittorrent_url")
    @classmethod
    def _a_configured_qbittorrent_url_must_be_one_the_guard_accepts(cls, value: str | None) -> str | None:
        """The same refusal as `jellyfin_base_url`, for the same reason (CLAUDE.md section 10.3, B21):
        a malformed base fails at BOOT, naming the variable, rather than at the first scan.

        This checks shape only - http(s), no embedded credentials, a parseable host and port - not
        whether the host is actually loopback or LAN. The client's own allowlist-of-one is what pins
        every call to this exact base once it is built.
        """
        if value is None:
            return None
        try:
            assert_within_configured_base(value, value)
        except OutboundUrlError as error:
            raise ValueError("TV_QBITTORRENT_URL must be an http or https origin with no credentials in it") from error
        return value

    # The import pipeline (Phase 3.5, ADR-015). `None` disables the staging-folder scan arm, exactly as
    # an absent provider credential disables a client - never a boot failure. The owner's real path is
    # typed into the root .env; no default here may name a personal directory.
    import_staging_dir: Path | None = None
    # The backend's own media directory. Compose sets it to /media (the same host directory
    # TV_JELLYFIN_MEDIA_HOST mounts into jellyfin, read-write for this service - T69); the launcher path
    # reads the owner's real value from the root .env. TV_JELLYFIN_MEDIA_HOST itself stays compose-only
    # and gets no Settings field, exactly as it does today.
    media_root: Path | None = None
    # How many files the staging-folder scan and identification passes work on at once.
    import_concurrency: int = Field(default=2, ge=1, le=8)

    @field_validator(
        "jellyfin_base_url",
        "jellyfin_api_key",
        "qbittorrent_url",
        "qbittorrent_user",
        "qbittorrent_password",
        mode="before",
    )
    @classmethod
    def _a_blank_line_is_the_disabled_feature(cls, value: object) -> object:
        """`TV_QBITTORRENT_USER=` in a .env means "I have not set this up", not "my username is empty".

        Without this the empty string is a VALUE: `configured` answers `True`, a login is posted with a
        blank username, and the owner meets a 403 rather than a disabled arm (R91). It runs `mode="before"`
        so the shape check below still sees every non-empty value, and it covers both configured upstreams
        so the rule is one rule rather than two that could diverge.
        """
        if isinstance(value, SecretStr):
            return None if value.get_secret_value() == "" else value
        return None if value == "" else value

    @property
    def database_url(self) -> str:
        """SQLAlchemy async URL. The password is only rendered here, never logged."""
        # URL.create escapes each component itself, so hand-quoting would double-encode it; building the
        # string by hand is what lets a `@`, `/`, `:` or `%` in a credential split the URL.
        return URL.create(
            drivername="postgresql+asyncpg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        ).render_as_string(hide_password=False)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton."""
    return Settings()
