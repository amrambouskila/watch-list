"""Failure modes of talking to a metadata provider.

None of these is registered in `api/errors.py`: a provider failure happens inside the ingest and lands
in `sync_state.last_error`, never in an HTTP response.
"""

from __future__ import annotations


class ProviderError(Exception):
    """Base class for metadata-provider failures."""


class ProviderNotConfiguredError(ProviderError):
    """The credential this provider needs is unset, so the ingest is disabled rather than broken."""


class OutboundUrlError(ProviderError):
    """The URL is not on the constant base this provider is pinned to."""


class ProviderResponseTooLargeError(ProviderError):
    """The response body passed the size cap and was refused rather than truncated."""


class ProviderUnavailableError(ProviderError):
    """The upstream could not be reached, timed out, or answered with something unusable."""


class ProviderRefusedError(ProviderError):
    """The upstream refused the call: a bad credential, a forbidden resource, or a rate limit."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class ProviderNotFoundError(ProviderError):
    """The upstream has no resource under that id."""


class UnknownSeasonTypeError(ProviderError):
    """The season type is not one the cached `GET /v4/seasons/types` list carries, so no URL is built."""


class QbittorrentNotConfiguredError(ProviderNotConfiguredError):
    """The URL, the username or the password is unset or blank, so the import's qBittorrent arm is off."""


class QbittorrentAuthError(ProviderError):
    """qBittorrent answered 403 - unauthenticated, or this IP is banned - so one re-login, never a loop."""


class QbittorrentUnsupportedVersionError(ProviderError):
    """The Web API is older than 2.8.2, so it does not send `content_path` or a file's `index`."""
