"""SSRF defence: the only URLs the agent may fetch are public http(s) endpoints."""

from __future__ import annotations

import socket

import pytest

from tv_watchlist.agent import url_guard
from tv_watchlist.agent.errors import BlockedUrlError

PUBLIC_ADDRESS = "93.184.216.34"


@pytest.fixture
def resolver(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[str]]:
    """Replace DNS so no test ever leaves the machine."""
    answers: dict[str, list[str]] = {}

    async def fake_resolve(host: str, port: int) -> list[str]:
        return answers[host]

    monkeypatch.setattr(url_guard, "resolve_addresses", fake_resolve)
    return answers


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.com/x", "gopher://example.com"])
async def test_a_non_http_scheme_is_refused(url: str, resolver: dict[str, list[str]]) -> None:
    with pytest.raises(BlockedUrlError):
        await url_guard.assert_public_http_url(url)


async def test_a_url_without_a_host_is_refused(resolver: dict[str, list[str]]) -> None:
    with pytest.raises(BlockedUrlError):
        await url_guard.assert_public_http_url("http:///nowhere")


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/admin",
        "http://[::1]/admin",
        "http://10.0.0.5/admin",
        "http://192.168.1.10/admin",
        "http://172.16.4.4/admin",
        "http://169.254.169.254/latest/meta-data",
        "http://[fd00::1]/admin",
    ],
)
async def test_a_literal_private_loopback_or_link_local_address_is_refused(
    url: str, resolver: dict[str, list[str]]
) -> None:
    with pytest.raises(BlockedUrlError):
        await url_guard.assert_public_http_url(url)


async def test_a_hostname_resolving_into_private_space_is_refused(resolver: dict[str, list[str]]) -> None:
    resolver["metadata.internal"] = ["169.254.169.254"]
    with pytest.raises(BlockedUrlError):
        await url_guard.assert_public_http_url("http://metadata.internal/latest")


async def test_a_hostname_is_refused_when_any_of_its_addresses_is_private(resolver: dict[str, list[str]]) -> None:
    resolver["split.example.com"] = [PUBLIC_ADDRESS, "10.1.2.3"]
    with pytest.raises(BlockedUrlError):
        await url_guard.assert_public_http_url("http://split.example.com/x")


async def test_a_public_hostname_is_allowed(resolver: dict[str, list[str]]) -> None:
    resolver["example.com"] = [PUBLIC_ADDRESS]
    await url_guard.assert_public_http_url("https://example.com/page")


async def test_a_public_literal_address_needs_no_dns_at_all(resolver: dict[str, list[str]]) -> None:
    await url_guard.assert_public_http_url(f"https://{PUBLIC_ADDRESS}/page")


@pytest.mark.parametrize("url", ["https://[::1", "https://example.com:99999/x"])
async def test_a_url_that_cannot_be_read_as_a_url_is_refused(url: str, resolver: dict[str, list[str]]) -> None:
    with pytest.raises(BlockedUrlError):
        await url_guard.assert_public_http_url(url)


async def test_a_hostname_that_does_not_resolve_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fails(host: str, port: int) -> list[str]:
        raise socket.gaierror(11001, "getaddrinfo failed")

    monkeypatch.setattr(url_guard, "resolve_addresses", fails)

    with pytest.raises(BlockedUrlError):
        await url_guard.assert_public_http_url("https://no-such-host.example/x")


async def test_a_hostname_that_answers_with_no_address_at_all_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    async def answers_with_nothing(host: str, port: int) -> list[str]:
        return []

    monkeypatch.setattr(url_guard, "resolve_addresses", answers_with_nothing)

    with pytest.raises(BlockedUrlError):
        await url_guard.assert_public_http_url("https://silent.example/x")
