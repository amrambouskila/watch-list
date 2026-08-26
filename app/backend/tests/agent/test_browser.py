"""Chromium starts on the first escalation, is shared, settles before it reads, and is torn down."""

from __future__ import annotations

import pytest
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from tv_watchlist.agent import browser
from tv_watchlist.agent.browser import ChromiumReader
from tv_watchlist.agent.constants import SETTLED_LOAD_STATE

RENDERED_TEXT = "Fury\nDunkirk"
LOST_CONTEXT_MESSAGE = "Execution context was destroyed, most likely because of a navigation"


class FakePage:
    def __init__(self, text: str, evaluate_failures: int = 0, *, never_settles: bool = False) -> None:
        self.text = text
        self.visited: str | None = None
        self.closed = False
        self.waited_states: list[str] = []
        self.evaluations = 0
        self._remaining_failures = evaluate_failures
        self._never_settles = never_settles

    async def goto(self, url: str, timeout: int, wait_until: str) -> None:
        self.visited = url

    async def wait_for_load_state(self, state: str, timeout: int) -> None:
        self.waited_states.append(state)
        if self._never_settles:
            raise PlaywrightTimeoutError(f"Timeout {timeout}ms exceeded waiting for {state}")

    async def evaluate(self, script: str) -> str:
        self.evaluations += 1
        if self._remaining_failures > 0:
            self._remaining_failures -= 1
            raise PlaywrightError(LOST_CONTEXT_MESSAGE)
        return self.text

    async def close(self) -> None:
        self.closed = True


class FakeBrowser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.evaluate_failures = 0
        self.never_settles = False
        self.pages: list[FakePage] = []
        self.closed = False

    async def new_page(self, user_agent: str) -> FakePage:
        page = FakePage(self.text, self.evaluate_failures, never_settles=self.never_settles)
        self.pages.append(page)
        return page

    async def close(self) -> None:
        self.closed = True


class FakeChromium:
    def __init__(self, browser_instance: FakeBrowser) -> None:
        self.browser = browser_instance
        self.launches = 0

    async def launch(self) -> FakeBrowser:
        self.launches += 1
        return self.browser


class FakeDriver:
    def __init__(self, chromium: FakeChromium) -> None:
        self.chromium = chromium
        self.stopped = False

    async def start(self) -> FakeDriver:
        return self

    async def stop(self) -> None:
        self.stopped = True


@pytest.fixture
def driver(monkeypatch: pytest.MonkeyPatch) -> FakeDriver:
    fake = FakeDriver(FakeChromium(FakeBrowser(RENDERED_TEXT)))
    monkeypatch.setattr(browser, "async_playwright", lambda: fake)
    return fake


async def test_no_browser_is_launched_until_the_first_page_is_read(driver: FakeDriver) -> None:
    ChromiumReader()

    assert driver.chromium.launches == 0


async def test_reading_a_page_returns_its_rendered_body_text(driver: FakeDriver) -> None:
    assert await ChromiumReader().read_text("https://example.com/list") == RENDERED_TEXT
    assert driver.chromium.browser.pages[0].visited == "https://example.com/list"


async def test_a_second_read_reuses_the_one_running_browser(driver: FakeDriver) -> None:
    reader = ChromiumReader()

    await reader.read_text("https://example.com/a")
    await reader.read_text("https://example.com/b")

    assert driver.chromium.launches == 1


async def test_every_page_is_closed_after_it_is_read(driver: FakeDriver) -> None:
    await ChromiumReader().read_text("https://example.com/a")

    assert driver.chromium.browser.pages[0].closed is True


async def test_closing_stops_both_the_browser_and_the_driver(driver: FakeDriver) -> None:
    reader = ChromiumReader()
    await reader.read_text("https://example.com/a")

    await reader.aclose()

    assert driver.chromium.browser.closed is True
    assert driver.stopped is True


async def test_closing_a_reader_that_never_started_is_harmless(driver: FakeDriver) -> None:
    await ChromiumReader().aclose()

    assert driver.stopped is False


async def test_a_page_is_read_only_once_the_browser_says_it_has_settled(driver: FakeDriver) -> None:
    await ChromiumReader().read_text("https://example.com/list")

    assert driver.chromium.browser.pages[0].waited_states == [SETTLED_LOAD_STATE]


async def test_a_read_lost_to_a_navigation_is_retried_once_against_the_settled_page(driver: FakeDriver) -> None:
    driver.chromium.browser.evaluate_failures = 1

    assert await ChromiumReader().read_text("https://example.com/list") == RENDERED_TEXT
    assert driver.chromium.browser.pages[0].waited_states == [SETTLED_LOAD_STATE, SETTLED_LOAD_STATE]


async def test_a_read_that_fails_twice_propagates_rather_than_being_swallowed(driver: FakeDriver) -> None:
    driver.chromium.browser.evaluate_failures = 2

    with pytest.raises(PlaywrightError):
        await ChromiumReader().read_text("https://example.com/list")


async def test_a_page_that_reads_first_time_is_not_evaluated_a_second_time(driver: FakeDriver) -> None:
    await ChromiumReader().read_text("https://example.com/list")

    assert driver.chromium.browser.pages[0].evaluations == 1


async def test_a_page_that_never_finishes_loading_is_still_read_as_it_stands(driver: FakeDriver) -> None:
    driver.chromium.browser.never_settles = True

    assert await ChromiumReader().read_text("https://example.com/live") == RENDERED_TEXT
    assert driver.chromium.browser.pages[0].evaluations == 1
