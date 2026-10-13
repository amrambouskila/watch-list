"""Pin every outbound provider call to its constant base, and build the URL without ever interpolating input."""

from __future__ import annotations

from typing import Final
from urllib.parse import quote, unquote, urlencode, urlsplit

from tv_watchlist.clients.errors import OutboundUrlError
from tv_watchlist.constants import TRAVERSAL_SEGMENT

_HTTPS: Final[str] = "https"
_HTTP: Final[str] = "http"
# What a provider on the public internet may be reached over, and what a configured LAN or loopback
# upstream the owner runs may be. The second set is wider by exactly one scheme and by nothing else.
_PUBLIC_SCHEMES: Final[frozenset[str]] = frozenset({_HTTPS})
_CONFIGURED_SCHEMES: Final[frozenset[str]] = frozenset({_HTTP, _HTTPS})


def _parts(url: str) -> tuple[str, str | None, int | None, str | None, str]:
    """A URL's scheme, host, port, username and path, refusing anything `urlsplit` cannot make sense of."""
    try:
        split = urlsplit(url)
        return split.scheme.lower(), split.hostname, split.port, split.username, split.path
    except ValueError as error:
        raise OutboundUrlError(f"{url} cannot be read as a URL ({error})") from error


def assert_within_base(url: str, base_url: str) -> None:
    """Raise `OutboundUrlError` unless `url` is https, on exactly the base host and port, and under its path."""
    _assert_within(url, base_url, allowed_schemes=_PUBLIC_SCHEMES)


def assert_within_configured_base(url: str, base_url: str) -> None:
    """Like `assert_within_base`, but allows `http` - for a configured LAN or loopback upstream the owner
    runs (Jellyfin, and later qBittorrent) - never a provider on the public internet.

    Same exact-host-and-port rule, same credentials-in-URL refusal, same traversal refusal, and the scheme
    must still match the configured base rather than merely being one of the two. `assert_within_base` stays
    the guard both provider clients are pinned by, and this sibling exists precisely so that relaxing the
    scheme here cannot relax it there.
    """
    _assert_within(url, base_url, allowed_schemes=_CONFIGURED_SCHEMES)


def _assert_within(url: str, base_url: str, *, allowed_schemes: frozenset[str]) -> None:
    """The whole rule, shared: scheme, credentials, exact host and port, no traversal, under the base path."""
    scheme, host, port, username, path = _parts(url)
    base_scheme, base_host, base_port, _, base_path = _parts(base_url)
    if base_scheme not in allowed_schemes:
        raise OutboundUrlError(f"{base_url} is not a base this guard accepts")
    # Equal to the BASE's scheme, not merely one of the permitted ones: with two schemes allowed, an https
    # URL against an http base is a different endpoint rather than the same one reached more carefully.
    if scheme != base_scheme:
        raise OutboundUrlError(f"{url} is not a {base_scheme} URL")
    if username is not None:
        raise OutboundUrlError(f"{url} carries credentials in the URL; providers are authenticated by header")
    # Exact host, never a suffix match: `api.themoviedb.org.evil` ends with the base host and is a
    # different server entirely.
    if host != base_host or port != base_port:
        raise OutboundUrlError(f"{url} is not on {base_scheme}://{base_host}")
    # Split AFTER unquoting: `..%2Fsecret` is one raw segment that becomes two once decoded.
    if any(TRAVERSAL_SEGMENT in unquote(segment).split("/") for segment in path.split("/")):
        raise OutboundUrlError(f"{url} walks out of the base path")
    prefix = base_path.rstrip("/")
    if path != prefix and not path.startswith(prefix + "/"):
        raise OutboundUrlError(f"{url} is not under {prefix or '/'}")


def _segment(value: int | str) -> str:
    """An int verbatim; a string with every reserved character percent-encoded so it cannot change the path."""
    return str(value) if isinstance(value, int) else quote(value, safe="")


def _built(base_url: str, segments: tuple[int | str, ...], query: dict[str, str | int | None]) -> str:
    """The base with these path segments and query values appended. Guarding it is the caller's half."""
    path = "/".join(_segment(segment) for segment in segments)
    url = base_url.rstrip("/") + "/" + path if path else base_url
    wanted = [(name, str(value)) for name, value in query.items() if value is not None]
    if wanted:
        url = url + "?" + urlencode(wanted, quote_via=quote, safe="")
    return url


def provider_url(base_url: str, *segments: int | str, **query: str | int | None) -> str:
    """The base with these path segments and query values appended, guarded against leaving the base."""
    url = _built(base_url, segments, query)
    assert_within_base(url, base_url)
    return url


def configured_url(base_url: str, *segments: int | str, **query: str | int | None) -> str:
    """`provider_url` for a configured LAN or loopback upstream the owner runs (Jellyfin, and later
    qBittorrent) - never a provider on the public internet: the same builder, ending on the `http`-tolerant
    guard.

    The Jellyfin client builds every URL with this and holds none, so there is no second builder anywhere
    and no method that hands a caller a URL it could log, paste or embed.
    """
    url = _built(base_url, segments, query)
    assert_within_configured_base(url, base_url)
    return url
