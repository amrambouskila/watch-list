from __future__ import annotations

from pathlib import Path
from typing import Final

import pytest

from env_example_support import ENV_EXAMPLE_PATH, env_example_entries, env_example_lines, settings_env_names

# `Settings` fields CLAUDE.md section 8.2 documents as never exposed for the owner to override through
# `.env.example`: each already has a fixed value under compose (a literal container path, e.g.
# `TV_LIBRARY_DIR=/library` in docker-compose.yml - not `${VAR:-default}` substitution) or a code-level
# default from `constants.py` that nothing overrides in practice ("Also set at: -- (prefix only)").
# Named and commented, rather than silently dropped, so a real gap - a `Settings` field that SHOULD gain
# a placeholder line - reads as a decision for the owner, never a line an agent adds on its own.
DECLARED_EXCLUSIONS: Final[frozenset[str]] = frozenset(
    {
        "TV_LIBRARY_DIR",  # compose fixes it to /library (docker-compose.yml:28); host default is REPO_ROOT
        "TV_BACKUP_DIR",  # compose fixes it to /library/app/.backups (docker-compose.yml:30)
        "TV_HEROES_DIR",  # compose fixes it to /library/app/heroes (docker-compose.yml:29)
        "TV_BACKUP_RETENTION",  # no compose or launcher override exists; the constants.py default stands
        "TV_BACKUP_INTERVAL_SECONDS",  # same - CLAUDE.md section 8.2 lists no "Also set at" for it either
    }
)
# Names in the file `Settings` does not read (yet): three compose-only substitutions, and the one Phase 3
# stub whose field lands at T55 (CLAUDE.md section 8.3). `extra="ignore"` on `Settings` means its presence
# in the environment is silently dropped until then. `TV_JELLYFIN_BASE_URL` and `TV_JELLYFIN_API_KEY` left
# this set at T48: they are real `Settings` fields now, so `settings_env_names()` supplies them.
# `TV_IMPORT_STAGING_HOST` joined at T60: the host-side name T69's compose mount substitutes from, the
# same split `TV_LIBRARY_HOST` / `TV_LIBRARY_DIR` already makes - no `Settings` field will ever read it.
DECLARED_EXTRAS: Final[frozenset[str]] = frozenset(
    {
        "TV_LIBRARY_HOST",  # compose-only: the host directory bind-mounted at /library
        "TV_JELLYFIN_PORT",  # compose-only: the host publication of the jellyfin service
        "TV_JELLYFIN_MEDIA_HOST",  # compose-only: the bind-mount source for /media
        "TV_STREAMING_AVAILABILITY_API_KEY",  # Phase 3 stub: Settings.streaming_availability_api_key lands at T55
        "TV_IMPORT_STAGING_HOST",  # compose-only: the host directory bind-mounted read-write at /staging (T69)
    }
)

EXPECTED_NAMES: Final[tuple[str, ...]] = (
    "TV_BACKEND_PORT",
    "TV_FRONTEND_PORT",
    "TV_LIBRARY_HOST",
    "TV_POSTGRES_HOST",
    "TV_POSTGRES_PORT",
    "TV_POSTGRES_DB",
    "TV_POSTGRES_USER",
    "TV_POSTGRES_PASSWORD",
    "TV_TMDB_READ_ACCESS_TOKEN",
    "TV_TVDB_API_KEY",
    "TV_TVDB_PIN",
    "TV_JELLYFIN_BASE_URL",
    "TV_JELLYFIN_API_KEY",
    "TV_JELLYFIN_PORT",
    "TV_JELLYFIN_MEDIA_HOST",
    "TV_STREAMING_AVAILABILITY_API_KEY",
    "TV_QBITTORRENT_URL",
    "TV_QBITTORRENT_USER",
    "TV_QBITTORRENT_PASSWORD",
    "TV_IMPORT_STAGING_DIR",
    "TV_MEDIA_ROOT",
    "TV_IMPORT_CONCURRENCY",
    "TV_IMPORT_STAGING_HOST",
)
SECRET_NAMES: Final[tuple[str, ...]] = (
    "TV_TMDB_READ_ACCESS_TOKEN",
    "TV_TVDB_API_KEY",
    "TV_TVDB_PIN",
    "TV_JELLYFIN_API_KEY",
    "TV_STREAMING_AVAILABILITY_API_KEY",
    "TV_QBITTORRENT_PASSWORD",
)
EXPECTED_DEFAULTS: Final[dict[str, str]] = {
    "TV_BACKEND_PORT": "8284",
    "TV_FRONTEND_PORT": "5284",
    "TV_LIBRARY_HOST": ".",
    "TV_POSTGRES_HOST": "localhost",
    "TV_POSTGRES_PORT": "5525",
    "TV_POSTGRES_DB": "tv",
    "TV_POSTGRES_USER": "tv",
    "TV_JELLYFIN_BASE_URL": "http://localhost:8096",
    "TV_JELLYFIN_PORT": "8096",
    "TV_JELLYFIN_MEDIA_HOST": "./media",
    "TV_QBITTORRENT_URL": "http://localhost:8080",
    "TV_IMPORT_CONCURRENCY": "2",
}
# `TV_IMPORT_STAGING_DIR` and `TV_MEDIA_ROOT` both default to `None` in `Settings` - deliberately absent
# from `EXPECTED_DEFAULTS`, the same reason no committed test pins a value for either: both must show a
# non-personal, machine-dependent example path rather than the owner's real directory (R68).
MACHINE_DEPENDENT_PATH_NAMES: Final[tuple[str, ...]] = ("TV_IMPORT_STAGING_DIR", "TV_MEDIA_ROOT")


def test_the_example_exists_at_the_repository_root() -> None:
    assert ENV_EXAMPLE_PATH.is_file(), f"{ENV_EXAMPLE_PATH} is missing"


def test_it_lists_every_variable_once_in_order() -> None:
    """Also the guard's tie to `Settings`: `EXPECTED_NAMES` must equal what `Settings` will read, plus
    the two declared exception tuples above - not only what this file happened to list by hand. A
    `Settings` field that gains a `TV_` name with no line here and no `DECLARED_EXCLUSIONS` entry now
    fails this test; so does an undeclared extra name in the file.
    """
    assert tuple(env_example_entries()) == EXPECTED_NAMES
    assert set(EXPECTED_NAMES) == (settings_env_names() - DECLARED_EXCLUSIONS) | DECLARED_EXTRAS


@pytest.mark.parametrize("name", SECRET_NAMES)
def test_a_secret_is_a_blank_placeholder(name: str) -> None:
    assert env_example_entries()[name] == ""


@pytest.mark.parametrize("name", sorted(EXPECTED_DEFAULTS))
def test_a_non_secret_carries_its_documented_default(name: str) -> None:
    assert env_example_entries()[name] == EXPECTED_DEFAULTS[name]


def test_every_variable_has_a_comment_line_directly_above_it() -> None:
    lines = env_example_lines()
    for index, line in enumerate(lines):
        if "=" in line and not line.lstrip().startswith("#"):
            assert lines[index - 1].lstrip().startswith("#"), f"{line.split('=')[0]} has no comment above it"


def test_no_line_carries_an_inline_comment() -> None:
    """docker compose and python-dotenv disagree on inline comments, so none are allowed."""
    for line in env_example_lines():
        if "=" in line and not line.lstrip().startswith("#"):
            assert "#" not in line, line


@pytest.mark.parametrize("name", MACHINE_DEPENDENT_PATH_NAMES)
def test_a_machine_dependent_path_carries_a_non_empty_non_personal_placeholder(name: str) -> None:
    """Both `import_staging_dir` and `media_root` default to `None` in `Settings`, so neither belongs
    in `EXPECTED_DEFAULTS` - but the committed file must still show a real-looking path rather than an
    empty `=` line, and never the owner's actual home directory (R68)."""
    value = env_example_entries()[name]
    assert value, f"{name} has no placeholder value"
    assert value not in {"~", str(Path.home())}
    assert not value.startswith(str(Path.home()))
