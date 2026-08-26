"""One lazily-started Chromium, shared by every fetch the cheap path could not read."""

from __future__ import annotations

import asyncio
from contextlib import suppress

from playwright.async_api import Browser, Error, Page, Playwright, async_playwright
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from tv_watchlist.agent.constants import (
    BROWSER_BODY_TEXT_SCRIPT,
    BROWSER_TIMEOUT_MS,
    FETCH_USER_AGENT,
    PAGE_LOAD_STATE,
    SETTLE_TIMEOUT_MS,
    SETTLED_LOAD_STATE,
)


class ChromiumReader:
    """Renders a page in a real browser and returns its visible body text."""

    def __init__(self) -> None:
        self._driver: Playwright | None = None
        self._browser: Browser | None = None
        self._launch_guard = asyncio.Lock()

    async def read_text(self, url: str) -> str:
        """The page's rendered body text, starting Chromium if this is the first escalation."""
        browser = await self._launched()
        page = await browser.new_page(user_agent=FETCH_USER_AGENT)
        try:
            await page.goto(url, timeout=BROWSER_TIMEOUT_MS, wait_until=PAGE_LOAD_STATE)
            try:
                return await self._settled_body_text(page)
            except Error:
                # A challenge page can navigate after it has settled, destroying the execution
                # context mid-read; one retry reads whatever the browser actually landed on.
                return await self._settled_body_text(page)
        finally:
            await page.close()

    async def aclose(self) -> None:
        """Shut down the browser and its driver; safe when nothing was ever started."""
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._driver is not None:
            await self._driver.stop()
            self._driver = None

    async def _settled_body_text(self, page: Page) -> str:
        """Body text once the page settles, or as it stands for one that never finishes loading."""
        # Streaming and long-polling pages never fire `load`, but their DOM is already there, so a
        # settle that times out is a reason to read now rather than to give up on the page.
        with suppress(PlaywrightTimeoutError):
            await page.wait_for_load_state(SETTLED_LOAD_STATE, timeout=SETTLE_TIMEOUT_MS)
        return str(await page.evaluate(BROWSER_BODY_TEXT_SCRIPT))

    async def _launched(self) -> Browser:
        """The one browser instance; the guard stops two concurrent escalations launching two."""
        async with self._launch_guard:
            if self._browser is None:
                self._driver = await async_playwright().start()
                self._browser = await self._driver.chromium.launch()
            return self._browser
