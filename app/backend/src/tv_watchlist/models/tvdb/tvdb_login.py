"""The answer to `POST /v4/login`."""

from __future__ import annotations

from pydantic import AliasPath, Field, SecretStr

from tv_watchlist.models.tvdb.tvdb_payload import TvdbPayload


class TvdbLogin(TvdbPayload):
    """`{"status": …, "data": {"token": …}}`. The token is a `SecretStr` so no repr or traceback renders it."""

    token: SecretStr = Field(validation_alias=AliasPath("data", "token"))
