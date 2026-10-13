"""The free-form `ProviderIds` map, and the one key this project reads out of it."""

from __future__ import annotations

import re
from typing import Final

from pydantic import ConfigDict, Field, RootModel

from tv_watchlist.constants import JELLYFIN_TMDB_PROVIDER_KEY

# A TMDB id as TMDB itself writes one: digits, nothing else. `int()` would also accept `+17`, ` 17 `,
# `17_2` and `-1`, each of which is a different row than the map meant - and one of them a row that
# could match a real id. Ten digits is the widest an `INTEGER` column can hold at all.
_DIGITS: Final[re.Pattern[str]] = re.compile(r"^\d{1,10}$")
# The largest value a Postgres `integer` takes; `title.tmdb_id` and `jellyfin_item.tmdb_id` are both one.
MAX_INTEGER_COLUMN_VALUE: Final[int] = 2_147_483_647


class JellyfinProviderIds(RootModel[dict[str, str | None]]):
    """Whatever ids Jellyfin's own scan found, kept verbatim, with `tmdb_id` the only reading of them.

    The schema types this as `additionalProperties: {"type": "string", "nullable": true}` with **no enum**,
    so the map is genuinely open and the TMDB key's casing is whatever the server chose. It is kept whole
    rather than narrowed to one field, because T49 confirms the casing against a live server and because
    the other ids (`Imdb`, `Tvdb`) are what a later diagnosis reads when a title will not match.
    """

    model_config = ConfigDict(frozen=True)

    root: dict[str, str | None] = Field(default_factory=dict)

    @property
    def tmdb_id(self) -> int | None:
        """The TMDB id, or `None` when there is no usable one. This is the Phase 3 join key.

        Matched case-insensitively against ONE constant, because `Tmdb` / `TMDB` / `tmdb` are all
        schema-valid and a case-sensitive `.get` would answer `None` for two of the three - which reads
        as "this file is not in your library" rather than as a lookup that missed.
        """
        wanted = JELLYFIN_TMDB_PROVIDER_KEY.casefold()
        for key, value in self.root.items():
            if key.casefold() == wanted:
                return _as_id(value)
        return None


def _as_id(value: str | None) -> int | None:
    """A map value as a TMDB id. Anything that is not plainly one is absent, never a row that reaches SQL.

    Matched against a digits-only pattern rather than handed to `int()`, and bounded by what the column
    can hold: a value `int()` would accept but Postgres would refuse is a failed INSERT in the middle of
    a library scan, and a value `int()` would silently normalise (`+17`, ` 17 `, `17_2`) is a claim about
    a title nobody wrote.
    """
    if value is None or _DIGITS.match(value) is None:
        return None
    parsed = int(value)
    return parsed if parsed <= MAX_INTEGER_COLUMN_VALUE else None
