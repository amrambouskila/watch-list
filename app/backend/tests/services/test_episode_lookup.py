"""The one lookup that turns a stored numbering into an episode (R70).

Two of these run against the recorded One Piece slice, because the whole point of the helper is that
`absolute` 62 is TMDB's `S02E62` - a fact only a real recording can assert. The rest run against synthetic
numberings, which is what a label and a title boundary need.

The database is real and the provider bodies are recorded: no socket is opened here (CLAUDE.md section 16.4).
"""

from __future__ import annotations

from typing import Final

from episode_join_support import A_FIRST_SEASON, SPECIALS_SEASON, a_show, one_piece_with_its_orderings
from ingest_support import THEIR_ABSOLUTE
from sqlalchemy.ext.asyncio import AsyncSession

from tv_watchlist.constants import SPECIALS_ORDER_LABEL
from tv_watchlist.ingest.episode_orders import AIRED_ORDER_TYPE, SPECIALS_ORDER_TYPE
from tv_watchlist.services.episode_lookup import episode_for_sequence

#: Laboon. The recorded slice numbers it absolute 62, and TMDB numbers it season 2, episode 62.
LABOON_ABSOLUTE: Final[int] = 62
LABOON_TMDB_SEASON: Final[int] = 2
#: Past the end of every ordering the recorded slice holds, by an order of magnitude.
A_SEQUENCE_NO_ORDERING_REACHES: Final[int] = 9_999
A_TYPE_ONE_PIECE_DOES_NOT_CARRY: Final[str] = "regional"
A_FEW_EPISODES: Final[int] = 4
A_FEW_SPECIALS: Final[int] = 2
FIRST: Final[int] = 1


async def test_episode_for_sequence_resolves_the_stored_numbering(db_session: AsyncSession) -> None:
    """Absolute 62 is not season 62, and it is not arithmetic either: it is the row the ingest wrote."""
    title = await one_piece_with_its_orderings(db_session)

    episode = await episode_for_sequence(db_session, title.id, THEIR_ABSOLUTE, sequence=LABOON_ABSOLUTE)

    assert episode is not None
    assert (episode.season_number, episode.episode_number) == (LABOON_TMDB_SEASON, LABOON_ABSOLUTE)


async def test_an_unknown_sequence_returns_none_rather_than_guessing(db_session: AsyncSession) -> None:
    """A slot past the end, and a numbering the title does not carry, are both nothing - never the aired rank."""
    title = await one_piece_with_its_orderings(db_session)

    beyond = await episode_for_sequence(db_session, title.id, THEIR_ABSOLUTE, sequence=A_SEQUENCE_NO_ORDERING_REACHES)
    unheld = await episode_for_sequence(db_session, title.id, A_TYPE_ONE_PIECE_DOES_NOT_CARRY, sequence=FIRST)

    assert beyond is None
    assert unheld is None


async def test_the_default_label_addresses_the_unlabelled_numbering(db_session: AsyncSession) -> None:
    """The specials bucket shares `alternate` with any provider ordering of that name; the label parts them."""
    title = await a_show(db_session, "A Show", episodes=A_FEW_EPISODES, specials=A_FEW_SPECIALS)

    aired = await episode_for_sequence(db_session, title.id, AIRED_ORDER_TYPE, sequence=FIRST)
    unlabelled = await episode_for_sequence(db_session, title.id, SPECIALS_ORDER_TYPE, sequence=FIRST)
    labelled = await episode_for_sequence(
        db_session, title.id, SPECIALS_ORDER_TYPE, SPECIALS_ORDER_LABEL, sequence=FIRST
    )

    assert aired is not None and aired.season_number == A_FIRST_SEASON
    assert unlabelled is None
    assert labelled is not None and labelled.season_number == SPECIALS_SEASON


async def test_a_sequence_is_answered_out_of_its_own_titles_numbering(db_session: AsyncSession) -> None:
    """Every title numbers from one, so the title is half the key and a lookup without it is a wrong episode."""
    one = await a_show(db_session, "One Show", episodes=A_FEW_EPISODES)
    another = await a_show(db_session, "Another Show", episodes=A_FEW_EPISODES)

    here = await episode_for_sequence(db_session, one.id, AIRED_ORDER_TYPE, sequence=FIRST)
    there = await episode_for_sequence(db_session, another.id, AIRED_ORDER_TYPE, sequence=FIRST)

    assert here is not None and there is not None
    assert here.id != there.id
    assert (here.title_id, there.title_id) == (one.id, another.id)
