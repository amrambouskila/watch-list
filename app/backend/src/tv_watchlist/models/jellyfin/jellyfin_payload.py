"""The shape every Jellyfin response model shares."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class JellyfinPayload(BaseModel):
    """Frozen, aliased to Jellyfin's PascalCase, and silently dropping keys this client never asked for."""

    # `extra="ignore"` is the untrusted-boundary rule (CLAUDE.md section 10.3, B16): `BaseItemDto` declares
    # 155 properties and the sync stores nine of them, so nothing unrequested can reach SQL by accident -
    # and a server that grows a key does not break a scan.
    # `populate_by_name` because every field here is aliased, unlike the TMDB and TheTVDB models whose wire
    # names are already snake_case: without it, T49's own tests could only build an item through its
    # PascalCase spelling.
    model_config = ConfigDict(extra="ignore", frozen=True, populate_by_name=True)
