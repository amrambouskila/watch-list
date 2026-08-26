"""Download one chosen candidate and make it a category's card artwork."""

from __future__ import annotations

import asyncio

import httpx

from tv_watchlist.agent.constants import FETCH_USER_AGENT
from tv_watchlist.agent.errors import HeroDownloadError, UnsafeHeroPathError, UnsupportedImageError
from tv_watchlist.agent.url_guard import assert_public_http_url
from tv_watchlist.config import Settings
from tv_watchlist.constants import HERO_ATTRIBUTION_FILENAME, HERO_FETCH_TIMEOUT_SECONDS, MAX_HERO_BYTES
from tv_watchlist.models.category_detail import CategoryDetail
from tv_watchlist.models.hero_candidate import HeroCandidate
from tv_watchlist.services.attribution import credit_hero_row
from tv_watchlist.services.catalog import Catalog
from tv_watchlist.services.hero_backup import retire_heroes
from tv_watchlist.services.image_format import image_suffix
from tv_watchlist.workbook.heroes import artwork_key
from tv_watchlist.workbook.locking import lock_for


async def _read_capped(response: httpx.Response, url: str) -> bytes:
    """The whole body, refused rather than truncated once it passes what a card image may weigh."""
    body = bytearray()
    async for chunk in response.aiter_bytes():
        body.extend(chunk)
        if len(body) > MAX_HERO_BYTES:
            raise HeroDownloadError(f"{url} is larger than the {MAX_HERO_BYTES} byte cap for card artwork")
    return bytes(body)


class HeroStore:
    """Turns a candidate URL into a validated image on disk, credited in the artwork table."""

    def __init__(self, catalog: Catalog, settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._catalog = catalog
        self._settings = settings
        self._transport = transport

    async def save(self, category_id: str, candidate: HeroCandidate) -> CategoryDetail:
        """Download the candidate, write it as this category's hero, and return the reloaded category."""
        detail = await self._catalog.detail(category_id)
        data = await self._download(candidate.url)
        suffix = image_suffix(data)
        if suffix is None:
            raise UnsupportedImageError(f"{candidate.url} did not serve a PNG, JPEG, GIF or WEBP image")
        heroes_dir = self._settings.heroes_dir
        # Retiring the standing artwork and writing its replacement is one act, and so is reading the
        # credit table and writing it back. Both are serialised on the registry the workbook layer
        # already uses -- the category first, then the table every category shares, in that order at
        # the one place that takes both, so two picks can never wait on each other.
        async with (
            lock_for(artwork_key(heroes_dir, detail.id)),
            lock_for(heroes_dir / HERO_ATTRIBUTION_FILENAME),
        ):
            await asyncio.to_thread(self._write, detail, candidate, suffix, data)
        return await self._catalog.detail(category_id)

    async def _download(self, url: str) -> bytes:
        """The bytes at a public http(s) address, under a timeout and a hard size cap."""
        await assert_public_http_url(url)
        async with httpx.AsyncClient(
            timeout=HERO_FETCH_TIMEOUT_SECONDS,
            # Every hop would have to be re-checked against the SSRF guard, so a direct file URL is
            # asked for instead and a redirect is simply reported back as a failure.
            follow_redirects=False,
            headers={"User-Agent": FETCH_USER_AGENT},
            transport=self._transport,
        ) as client:
            try:
                async with client.stream("GET", url) as response:
                    if not response.is_success:
                        raise HeroDownloadError(f"{url} answered {response.status_code}")
                    return await _read_capped(response, url)
            # `InvalidURL` is raised while building the request and is not an `HTTPError`, so a URL
            # httpx itself refuses would otherwise leave this call as an unhandled crash.
            except (httpx.HTTPError, httpx.InvalidURL) as error:
                raise HeroDownloadError(f"{url} could not be read ({type(error).__name__})") from error

    def _write(self, detail: CategoryDetail, candidate: HeroCandidate, suffix: str, data: bytes) -> None:
        """Replace whatever hero this category had, and credit the image that replaced it."""
        heroes_dir = self._settings.heroes_dir
        heroes_dir.mkdir(parents=True, exist_ok=True)
        heroes_dir = heroes_dir.resolve()
        destination = (heroes_dir / f"{detail.id}{suffix}").resolve()
        # The id is derived from a real workbook filename rather than taken from the model, so this
        # cannot fire; it is here so that stops being something a reader has to verify elsewhere.
        if not destination.is_relative_to(heroes_dir):
            raise UnsafeHeroPathError(f"{destination} is outside {heroes_dir}")
        retire_heroes(heroes_dir, self._settings.backup_dir, detail.id)
        destination.write_bytes(data)
        credit_hero_row(heroes_dir / HERO_ATTRIBUTION_FILENAME, detail.name, candidate)
