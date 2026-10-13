"""One item as Jellyfin reports it: a movie, a series or an episode."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import Field, field_validator

from tv_watchlist.constants import (
    MAX_JELLYFIN_ID_LENGTH,
    MAX_JELLYFIN_NAME_LENGTH,
    MAX_JELLYFIN_PATH_LENGTH,
    TICKS_PER_SECOND,
)
from tv_watchlist.models.jellyfin.jellyfin_payload import JellyfinPayload
from tv_watchlist.models.jellyfin.jellyfin_provider_ids import JellyfinProviderIds


class JellyfinItemDto(JellyfinPayload):
    """The nine `BaseItemDto` fields the library index is built from, carried verbatim.

    `ParentIndexNumber`, `IndexNumber` and `IndexNumberEnd` are Jellyfin's own season, episode and
    last-episode-of-a-multi-episode-file numbers, and they are **never reinterpreted here**: what they mean
    is whatever the file naming produced, and the ordering they belong to is resolved against TheTVDB before
    any join (CLAUDE.md section 20.2, item 3).

    Only `Id` is required, and that is a decision rather than an oversight: `BaseItemDtoQueryResult` marks
    nothing required, so every other field has to survive being absent, but an item with no id is one the
    sync could not key on at all - failing loudly on that is better than storing a blank.
    """

    id: str = Field(alias="Id", max_length=MAX_JELLYFIN_ID_LENGTH)
    # `Name` is nullable in the schema, so one nameless file must not cost a whole library scan.
    name: str = Field(alias="Name", default="", max_length=MAX_JELLYFIN_NAME_LENGTH)
    kind: str = Field(alias="Type")
    provider_ids: JellyfinProviderIds = Field(alias="ProviderIds", default_factory=JellyfinProviderIds)
    path: str | None = Field(alias="Path", default=None, max_length=MAX_JELLYFIN_PATH_LENGTH)
    series_id: str | None = Field(alias="SeriesId", default=None, max_length=MAX_JELLYFIN_ID_LENGTH)
    parent_index_number: int | None = Field(alias="ParentIndexNumber", default=None)
    index_number: int | None = Field(alias="IndexNumber", default=None)
    index_number_end: int | None = Field(alias="IndexNumberEnd", default=None)
    # Named for the unit it holds, and aliased from the unit the wire holds. Ticks are converted on the way
    # IN (CLAUDE.md section 11.2, rule 7) and are deliberately not a field beside this one: two attributes
    # for one duration is how a second, different conversion eventually gets written somewhere downstream.
    run_time_seconds: int | None = Field(alias="RunTimeTicks", default=None, ge=0)
    # 12.1's `BaseItemDto` does not declare this and sets `additionalProperties: false`, even though
    # `DateLastSaved` IS a valid `ItemFields` value and `minDateLastSaved` IS a valid filter. It is read
    # when a server sends it and is simply absent when one does not; T49 confirms which
    # (tests/fixtures/jellyfin/README.md).
    date_last_saved: datetime | None = Field(alias="DateLastSaved", default=None)

    @field_validator("name", mode="before")
    @classmethod
    def _a_null_name_is_a_blank_one(cls, value: object) -> object:
        """A null `Name` is a nameless file, not a body to refuse."""
        return "" if value is None else value

    @field_validator("provider_ids", mode="before")
    @classmethod
    def _a_null_provider_map_is_an_empty_one(cls, value: object) -> object:
        """No ids is a real state, and it is the whole `not_in_library` half of a library."""
        return {} if value is None else value

    @field_validator("date_last_saved", mode="after")
    @classmethod
    def _a_naive_stamp_is_read_as_utc(cls, value: datetime | None) -> datetime | None:
        """Jellyfin's `DateLastSaved` is UTC; a server that omits the offset must not become a naive value.

        `jellyfin_item.date_last_saved` is `DateTime(timezone=True)`, and asyncpg refuses a naive datetime
        for one - so an offsetless stamp would fail the INSERT halfway through a scan rather than at this
        boundary. Which of the three ISO spellings 12.1 really sends is one of the fixtures README's open
        questions, so this accepts all of them and normalises here (CLAUDE.md section 11.2, rule 7's habit:
        convert once, at the boundary).
        """
        if value is None or value.tzinfo is not None:
            return value
        return value.replace(tzinfo=UTC)

    @field_validator("run_time_seconds", mode="before")
    @classmethod
    def _ticks_become_whole_seconds_here_and_nowhere_else(cls, value: object) -> object:
        """`.NET` ticks are 100 ns, so seconds are `ticks // 10_000_000` - converted once, at this boundary.

        Floor division, so a negative tick count stays negative and `ge=0` refuses it rather than rounding
        it into a plausible zero.
        """
        if isinstance(value, bool) or not isinstance(value, int):
            return value
        return value // TICKS_PER_SECOND
