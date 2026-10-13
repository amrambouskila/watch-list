"""The shape every qBittorrent response model shares."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class QbittorrentPayload(BaseModel):
    """Frozen, and silently dropping the fields this client never asked for."""

    # `extra="ignore"` is the untrusted-boundary rule (CLAUDE.md section 10.3, B21): the torrent list
    # carries some fifty fields and this client reads nine of them, so nothing unrequested can reach SQL
    # or a path by accident - and a WebUI that grows a key does not break a scan.
    # No aliases: qBittorrent's wire names are already snake_case, unlike Jellyfin's PascalCase ones.
    model_config = ConfigDict(extra="ignore", frozen=True)
