"""One piece of artwork Claude found, offered for a category card."""

from __future__ import annotations

from pydantic import BaseModel, Field

from tv_watchlist.constants import (
    HTTP_URL_PATTERN,
    MAX_HERO_DESCRIPTION_LENGTH,
    MAX_HERO_LICENCE_LENGTH,
    MAX_HERO_SOURCE_FILE_LENGTH,
    MAX_HERO_URL_LENGTH,
)


class HeroCandidate(BaseModel):
    """A freely-licensed image: where to download it, what it is, and who says it is free."""

    # The app downloads `url` and the dock links `page`, so neither may carry a scheme that means
    # anything other than "fetch this over the web".
    url: str = Field(max_length=MAX_HERO_URL_LENGTH, pattern=HTTP_URL_PATTERN)
    source_file: str = Field(max_length=MAX_HERO_SOURCE_FILE_LENGTH)
    licence: str = Field(max_length=MAX_HERO_LICENCE_LENGTH)
    page: str = Field(max_length=MAX_HERO_URL_LENGTH, pattern=HTTP_URL_PATTERN)
    description: str = Field(max_length=MAX_HERO_DESCRIPTION_LENGTH)
