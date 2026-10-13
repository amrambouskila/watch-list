"""One human decision about one curated entry's resolution."""

from __future__ import annotations

from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from tv_watchlist.constants import MAX_REASON_LENGTH
from tv_watchlist.data.enums import MediaType, UnitKind

ReviewAction = Literal["confirm", "correct", "reject"]

CONFIRM: Final[ReviewAction] = "confirm"
CORRECT: Final[ReviewAction] = "correct"
REJECT: Final[ReviewAction] = "reject"

# `curated_entry.order_type` is String(32). Clipped here so a body that could not be stored is refused
# at the boundary rather than at the flush, where the failure names a constraint instead of a field.
MAX_ORDER_TYPE_LENGTH: Final[int] = 32

# Everything a `correct` may carry beyond the action and the note. `confirm` and `reject` carry none of
# it: a decision that says "this is right" while also naming a different title is two decisions, and a
# server that picked one of them would be guessing (CLAUDE.md section 18.2).
_CORRECTION_FIELDS: Final[tuple[str, ...]] = (
    "media_type",
    "tmdb_id",
    "unit_kind",
    "order_type",
    "span_start",
    "span_end",
    "season_number",
)


class ResolutionUpdate(BaseModel):
    """A human decision about one entry.

    `confirm` carries no field but the note; `correct` requires `media_type` and `tmdb_id` and takes the
    span fields optionally; `reject` carries the note alone.
    """

    model_config = ConfigDict(extra="forbid")

    action: ReviewAction
    media_type: MediaType | None = None
    tmdb_id: int | None = Field(default=None, ge=1)
    unit_kind: UnitKind | None = None
    # An open string, validated at apply time against the numberings the title actually carries, never
    # against a list in this codebase: TheTVDB's season types are read at runtime and are not a closed
    # set (CLAUDE.md section 5.13).
    order_type: str | None = Field(default=None, max_length=MAX_ORDER_TYPE_LENGTH)
    span_start: int | None = Field(default=None, ge=1)
    span_end: int | None = Field(default=None, ge=1)
    # Season 0 is the specials bucket and is kept, so this floor is zero rather than one.
    season_number: int | None = Field(default=None, ge=0)
    note: str = Field(default="", max_length=MAX_REASON_LENGTH)

    @model_validator(mode="after")
    def _coherent_for_its_action(self) -> ResolutionUpdate:
        if self.action == CORRECT:
            if self.media_type is None or self.tmdb_id is None:
                raise ValueError("a correct names the title it corrects to: media_type and tmdb_id are both required")
        elif any(getattr(self, name) is not None for name in _CORRECTION_FIELDS):
            raise ValueError(f"a {self.action} carries no title or span fields, only a note")
        if self.span_start is not None and self.span_end is not None and self.span_end < self.span_start:
            raise ValueError("span_end is before span_start")
        return self
