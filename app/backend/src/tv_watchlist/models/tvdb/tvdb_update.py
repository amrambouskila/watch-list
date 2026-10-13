"""One row of the updates feed."""

from __future__ import annotations

from pydantic import Field

from tv_watchlist.models.tvdb.tvdb_payload import TvdbPayload


class TvdbUpdate(TvdbPayload):
    """Which record moved, when, and under which series - the cursor a refresh walks instead of refetching all."""

    record_id: int = Field(default=0, validation_alias="recordId")
    record_type: str = Field(default="", validation_alias="recordType")
    entity_type: str = Field(default="", validation_alias="entityType")
    method: str = ""
    time_stamp: int = Field(default=0, validation_alias="timeStamp")
    series_id: int | None = Field(default=None, validation_alias="seriesId")
    merge_to_id: int | None = Field(default=None, validation_alias="mergeToId")
