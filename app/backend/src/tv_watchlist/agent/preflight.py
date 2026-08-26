"""What the chat feature needs on the machine, checked before the launcher promises it works."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Final

CLI_EXECUTABLE: Final[str] = "claude"
BROWSERS_PATH_VARIABLE: Final[str] = "PLAYWRIGHT_BROWSERS_PATH"
BROWSERS_DIRNAME: Final[str] = "ms-playwright"
CHROMIUM_BUILD_GLOB: Final[str] = "chromium-*"
CHROMIUM_EXECUTABLE_GLOB: Final[str] = "chrome*"
CLI_ADVICE: Final[str] = (
    "Claude Code is not on PATH, so chat will answer 503. "
    "Install it, then reopen this shell: npm i -g @anthropic-ai/claude-code"
)
CHROMIUM_ADVICE: Final[str] = (
    "Playwright's Chromium is not downloaded, so bot-blocked pages cannot be read. "
    "Run: uv run playwright install chromium"
)


def installed_cli() -> Path | None:
    """Where `claude` lives on PATH, or None. The SDK ships no binary and shells out to this."""
    found = shutil.which(CLI_EXECUTABLE)
    return Path(found) if found is not None else None


def browsers_dir() -> Path:
    """Where Playwright keeps its downloads: its documented override first, then the per-OS cache."""
    override = os.environ.get(BROWSERS_PATH_VARIABLE)
    if override:
        return Path(override)
    if sys.platform == "win32":
        return Path(os.environ["LOCALAPPDATA"]) / BROWSERS_DIRNAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / BROWSERS_DIRNAME
    return Path.home() / ".cache" / BROWSERS_DIRNAME


def installed_chromium() -> Path | None:
    """The downloaded Chromium build the blocked-URL path falls back to, or None."""
    builds = sorted(build for build in browsers_dir().glob(CHROMIUM_BUILD_GLOB) if build.is_dir())
    return next((build for build in builds if any(f.is_file() for f in build.rglob(CHROMIUM_EXECUTABLE_GLOB))), None)


def missing_requirements() -> list[str]:
    """One line per missing requirement, naming what to run to get it."""
    reported = []
    if installed_cli() is None:
        reported.append(CLI_ADVICE)
    if installed_chromium() is None:
        reported.append(CHROMIUM_ADVICE)
    return reported


if __name__ == "__main__":
    for requirement in missing_requirements():
        print(f"  {requirement}")
