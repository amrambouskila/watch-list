"""The on-disk byte cache for provider artwork (CLAUDE.md section 10.3, B11).

Artwork bytes never live in Postgres. `artwork.local_path` points into `heroes_dir`, which already owns
image caching, licence attribution and cache-busting, so this reuses B5's machinery rather than standing
up a second downloader: the same SSRF guard, the same `follow_redirects=False`, the same size cap, the
same magic-byte check, the same resolve-and-confine on the destination.

Two things are different from B5, and both are deliberate. The URL is **composed** -
`secure_base_url + size + remote_path` - so no payload ever hands this module a URL. And no refusal
raises: an ingest that cannot cache a poster has still ingested a title, so every refusal is a logged
`None`.
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import Final

import httpx

from tv_watchlist.agent.constants import FETCH_USER_AGENT
from tv_watchlist.agent.errors import BlockedUrlError, HeroDownloadError
from tv_watchlist.agent.url_guard import assert_public_http_url
from tv_watchlist.config import Settings
from tv_watchlist.constants import (
    ARTWORK_SUBDIR,
    HERO_FETCH_TIMEOUT_SECONDS,
    MAX_ARTWORK_BYTES_PER_RUN,
    MAX_HERO_BYTES,
    TMDB_POSTER_SIZE,
    TMDB_REMOTE_PATH_PATTERN,
)
from tv_watchlist.data.models import Artwork
from tv_watchlist.services.hero_store import read_capped
from tv_watchlist.services.image_format import image_suffix

_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)

_REMOTE_PATH: Final[re.Pattern[str]] = re.compile(TMDB_REMOTE_PATH_PATTERN)
# A size is a bare slug this app chose - `w500`, `original`. Checked anyway, because it lands in a path.
_SIZE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9]+$")
# The base arrives inside `GET /3/configuration`, which is a provider payload like any other, so it is
# pinned to https and required to be a directory: the composition appends a size straight onto it.
_SECURE_SCHEME: Final[str] = "https://"
_PATH_SEPARATOR: Final[str] = "/"
# A crafted value must not be able to end a log record and forge another (CLAUDE.md, header/log injection).
_NEWLINES: Final[dict[int, None]] = str.maketrans("", "", "\r\n")


def remote_path_is_safe(remote_path: str) -> bool:
    """Whether a stored `artwork.remote_path` may be composed into a URL at all.

    One leading slash and no second one, no dot-segment, no percent escape, no query, and a raster
    extension. Everything a traversal or a host swap would need is outside the character class.
    """
    return _REMOTE_PATH.match(remote_path) is not None


class ArtworkCache:
    """Downloads one artwork's bytes into `heroes_dir/tmdb/<artwork id>.<suffix>`, or refuses and says so."""

    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._settings = settings
        self._transport = transport
        self._spent_bytes = 0

    @property
    def spent_bytes(self) -> int:
        """How much of this pass's artwork budget has been used."""
        return self._spent_bytes

    def spend(self, count: int) -> None:
        """Charge bytes against the run budget. Public so a caller can share one budget across passes."""
        self._spent_bytes += count

    async def ensure_cached(
        self, artwork: Artwork, *, secure_base_url: str, size: str = TMDB_POSTER_SIZE
    ) -> Path | None:
        """The cached file for this row, fetching it if it is not there yet. `None` is a refusal, never a raise."""
        standing = self._standing(artwork)
        if standing is not None:
            return standing
        url = self._composed(artwork.remote_path, secure_base_url, size)
        if url is None:
            return None
        if self._spent_bytes >= MAX_ARTWORK_BYTES_PER_RUN:
            self._refused(artwork, "run-budget-spent")
            return None
        data = await self._downloaded(artwork, url)
        if data is None:
            return None
        suffix = image_suffix(data)
        if suffix is None:
            # SVG is absent from `image_suffix` on purpose: it is scriptable XML.
            self._refused(artwork, "not-a-raster-image")
            return None
        return await self._written(artwork, suffix, data)

    def _standing(self, artwork: Artwork) -> Path | None:
        """The file this row already points at, when it is still there. A cache that refetches is not one."""
        if artwork.local_path is None:
            return None
        root = self._settings.heroes_dir.resolve()
        existing = (root / artwork.local_path).resolve()
        if not existing.is_relative_to(root) or not existing.is_file():
            # A stored path that has left the directory, or a file the owner has since deleted: both mean
            # the row is pointing at nothing, so the next call fetches rather than trusting the column.
            return None
        return existing

    def _composed(self, remote_path: str, secure_base_url: str, size: str) -> str | None:
        """`secure_base_url + size + remote_path`, or `None` when any of the three is not what it claims."""
        if not remote_path_is_safe(remote_path):
            self._logged("refused", remote_path=remote_path, reason="unsafe-remote-path")
            return None
        if not secure_base_url.startswith(_SECURE_SCHEME) or not secure_base_url.endswith(_PATH_SEPARATOR):
            self._logged("refused", remote_path=remote_path, reason="unsafe-image-base")
            return None
        if _SIZE.match(size) is None:
            self._logged("refused", remote_path=remote_path, reason="unsafe-size")
            return None
        return f"{secure_base_url}{size}{remote_path}"

    async def _downloaded(self, artwork: Artwork, url: str) -> bytes | None:
        """The bytes at a composed, publicly-routable URL, under a timeout, a hard cap and no redirects."""
        try:
            await assert_public_http_url(url)
        except BlockedUrlError:
            self._refused(artwork, "blocked-url")
            return None
        async with httpx.AsyncClient(
            timeout=HERO_FETCH_TIMEOUT_SECONDS,
            # A hop would have to be re-vetted against the guard, so a direct file URL is required and a
            # redirect is reported back as the refusal it is.
            follow_redirects=False,
            headers={"User-Agent": FETCH_USER_AGENT},
            transport=self._transport,
        ) as client:
            try:
                async with client.stream("GET", url) as response:
                    if not response.is_success:
                        self._refused(artwork, f"status-{response.status_code}")
                        return None
                    try:
                        data = await read_capped(response, url)
                    except HeroDownloadError as error:
                        # The wire carried those bytes whether or not any of them were kept, so a refused
                        # giant is not free: charging only the downloads that succeeded would let one
                        # oversized image per title walk straight past the run budget. `read_capped`
                        # refuses at the first chunk past the cap, so the cap is the floor; httpx's own
                        # counter is the exact figure where it has one, and is 0 behind a mock transport.
                        self.spend(max(response.num_bytes_downloaded, MAX_HERO_BYTES))
                        self._refused(artwork, type(error).__name__)
                        return None
            # `InvalidURL` is raised while the request is built and is not an `HTTPError`, so a URL httpx
            # itself refuses would otherwise escape as a crash into the middle of an ingest.
            except (httpx.HTTPError, httpx.InvalidURL) as error:
                self._refused(artwork, type(error).__name__)
                return None
        self.spend(len(data))
        return data

    async def _written(self, artwork: Artwork, suffix: str, data: bytes) -> Path | None:
        """The file, named by this row's UUID and confined to the artwork directory under `heroes_dir`."""
        heroes_dir = self._settings.heroes_dir
        directory = heroes_dir / ARTWORK_SUBDIR
        await asyncio.to_thread(directory.mkdir, parents=True, exist_ok=True)
        root = heroes_dir.resolve()
        destination = (root / ARTWORK_SUBDIR / f"{artwork.id}{suffix}").resolve()
        # The name is a UUID this app minted, so this cannot fire; it is here so that stops being
        # something a reader has to go and verify somewhere else.
        if not destination.is_relative_to(root):
            self._refused(artwork, "outside-heroes-dir")
            return None
        await asyncio.to_thread(destination.write_bytes, data)
        # Relative: `heroes_dir` differs between the launcher path and the container, and `/heroes` is
        # served from that directory, so what is stored is exactly the tail of the URL that serves it.
        artwork.local_path = f"{ARTWORK_SUBDIR}{_PATH_SEPARATOR}{destination.name}"
        self._logged("cached", remote_path=artwork.remote_path, reason="fresh", bytes_read=len(data))
        return destination

    def _refused(self, artwork: Artwork, reason: str) -> None:
        self._logged("refused", remote_path=artwork.remote_path, reason=reason)

    def _logged(self, event: str, *, remote_path: str, reason: str, bytes_read: int = 0) -> None:
        """One key=value record. Never a header, never a credential, never a body."""
        _LOGGER.info(
            "artwork_cache event=%s remote_path=%s reason=%s bytes=%d",
            _scrubbed(event),
            _scrubbed(remote_path),
            _scrubbed(reason),
            bytes_read,
        )


def _scrubbed(value: str) -> str:
    return value.translate(_NEWLINES)
