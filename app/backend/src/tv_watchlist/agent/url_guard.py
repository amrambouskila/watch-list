"""Reject any URL the agent must not reach, before a request is made and again on every redirect."""

from __future__ import annotations

from ipaddress import ip_address
from urllib.parse import urlsplit

from tv_watchlist.agent.address_lookup import resolve_addresses
from tv_watchlist.agent.constants import DEFAULT_PORT_BY_SCHEME, HTTP_SCHEMES
from tv_watchlist.agent.errors import BlockedUrlError


def _is_reachable(address: str) -> bool:
    parsed = ip_address(address)
    return not (
        parsed.is_private
        or parsed.is_loopback
        or parsed.is_link_local
        or parsed.is_multicast
        or parsed.is_reserved
        or parsed.is_unspecified
    )


def _target(url: str) -> tuple[str, int]:
    """The host and port a URL points at, refusing anything `urlsplit` cannot make sense of."""
    try:
        parts = urlsplit(url)
        scheme = parts.scheme.lower()
        if scheme not in HTTP_SCHEMES:
            raise BlockedUrlError(f"{parts.scheme or url!r} is not an http(s) URL")
        host = parts.hostname
        port = parts.port or DEFAULT_PORT_BY_SCHEME[scheme]
    except ValueError as error:
        raise BlockedUrlError(f"{url} cannot be read as a URL ({error})") from error
    if not host:
        raise BlockedUrlError(f"{url} has no host")
    return host, port


async def _resolved(host: str, port: int) -> list[str]:
    """Every address a hostname answers with; one that answers with none is one we cannot vet."""
    try:
        addresses = await resolve_addresses(host, port)
    except OSError as error:
        raise BlockedUrlError(f"{host} does not resolve ({type(error).__name__})") from error
    if not addresses:
        raise BlockedUrlError(f"{host} resolves to no address at all")
    return addresses


async def assert_public_http_url(url: str) -> None:
    """Raise `BlockedUrlError` unless this is an http(s) URL whose every address is publicly routable."""
    host, port = _target(url)
    try:
        addresses = [str(ip_address(host))]
    except ValueError:
        addresses = await _resolved(host, port)
    blocked = next((address for address in addresses if not _is_reachable(address)), None)
    if blocked is not None:
        raise BlockedUrlError(f"{host} resolves to {blocked}, which is not publicly routable")
