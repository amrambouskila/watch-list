"""`episode_order`: the aired rank this app computes, and every ordering TheTVDB offers at runtime.

Two halves. The pure half - the rank walks, the provider ranking, the loop detector, the ordering-name
rule, the cursor key - runs anywhere. The half that writes runs against a real Postgres and skips loudly
without one; a mocked database would prove only that the mock agrees with itself (CLAUDE.md 16.4).

Provider traffic is recorded fixtures through an `httpx.MockTransport`. Nothing here reaches a network.

The reference episode is One Piece's Laboon, and it is the whole point of the table: one `episode.id`
carrying four numberings that disagree about every number except which episode it is.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator, Sequence
from datetime import date
from pathlib import Path
from typing import Final

import pytest
from ingest_support import (
    A_TYPE_THE_APP_HAS_NEVER_SEEN,
    ONE_PIECE,
    ONE_PIECE_TVDB,
    RECORDED_ORDERINGS,
    RECORDED_SEASONS,
    REGULAR_EPISODES,
    SPECIALS,
    THEIR_ABSOLUTE,
    THEIR_AIRED,
    THEIR_DISC,
    order_ingest,
    recorded_episodes,
    recorded_page_episodes,
    seeded_one_piece,
)
from sqlalchemy import select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from provider_fixtures import (
    TVDB,
    fixture_json,
)
from statement_support import counted_statements
from tv_watchlist.constants import (
    SPECIALS_ORDER_LABEL,
)
from tv_watchlist.data.enums import ExternalSource, MediaType, SyncResourceType
from tv_watchlist.data.models import Episode, EpisodeOrder, Season, SyncState, Title
from tv_watchlist.ingest.episode_orders import (
    AIRED_ORDER_TYPE,
    NO_LABEL,
    ORDER_TYPE_LENGTH,
    SPECIALS_ORDER_TYPE,
    EpisodeOrderIngest,
    OrderSlot,
    aired_slots,
    comparable_row,
    episodes_key,
    order_values,
    provider_order_type,
    provider_slots,
    ranked,
    refusal_for,
    repeated_provider_ids,
    resource_label,
    specials_slots,
    summed,
    tvdb_series_id_for,
)
from tv_watchlist.ingest.ingest_outcome import IngestOutcome
from tv_watchlist.ingest.sync_cursor import PostgresResponseCache
from tv_watchlist.ingest.tvdb_matching import StoredEpisode, match_tvdb_episodes
from tv_watchlist.models.tvdb.tvdb_episode import TvdbEpisode

# The reference episode (docs/status.md section 2.9). One episode row, four numberings.
LABOON_TMDB_EPISODE_ID: Final[int] = 1146416
LABOON_TVDB_EPISODE_ID: Final[int] = 361955
LABOON_AIRED_SEQUENCE: Final[int] = 62
LABOON_TMDB_PAIR: Final[tuple[int, int]] = (2, 62)

# What each recorded ordering pairs with the recorded TMDB slice, and where Laboon lands in it.
# The disc ordering pairs one more than the absolute one: its second page carries a TV special that
# the recorded specials bucket also holds, and the absolute ordering does not list specials at all.
WRITTEN_ROWS: Final[dict[str, int]] = {THEIR_AIRED: 113, THEIR_ABSOLUTE: 77, THEIR_DISC: 78}
LABOON_IN: Final[dict[str, tuple[int, int, int]]] = {
    # order_type -> (sequence, order_season_number, order_episode_number)
    THEIR_AIRED: (98, 5, 2),
    THEIR_ABSOLUTE: (62, 1, 62),
    THEIR_DISC: (62, 2, 1),
}
# The season-type names that must appear nowhere in the ingest's own source: the list is read at runtime.
FORBIDDEN_LITERALS: Final[tuple[str, ...]] = (THEIR_AIRED, THEIR_DISC, "altdvd", "alttwo", "regional")

AN_EPISODE_NUMBER_NO_RECORDED_SEASON_USES: Final[int] = 900
A_TMDB_EPISODE_ID_NO_FIXTURE_USES: Final[int] = 99_000_001


# -- pure helpers -----------------------------------------------------------------------------------


def an_id(seed: int) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_OID, str(seed))


def a_numbering(*pairs: tuple[int, int]) -> tuple[tuple[uuid.UUID, int, int], ...]:
    """`(episode_id, season_number, episode_number)` triples, ids minted from the pair's position."""
    return tuple((an_id(index), season, episode) for index, (season, episode) in enumerate(pairs))


def a_tvdb_episode(provider_id: int, *, season: int, number: int) -> TvdbEpisode:
    return TvdbEpisode.model_validate({"id": provider_id, "seasonNumber": season, "number": number})


def an_episode_id(tmdb_episode_id: int) -> uuid.UUID:
    """A stand-in for the row id the projection mints, so the pure half can pin the same numbers."""
    return uuid.uuid5(uuid.NAMESPACE_OID, str(tmdb_episode_id))


def recorded_numbering() -> tuple[tuple[uuid.UUID, int, int], ...]:
    """The recorded TMDB slice as `(episode_id, season_number, episode_number)` triples."""
    return tuple(
        (an_episode_id(episode["id"]), episode["season_number"], episode["episode_number"])
        for season in RECORDED_SEASONS
        for episode in recorded_episodes(season)
    )


def recorded_stored_episodes() -> tuple[StoredEpisode, ...]:
    """The same slice as the matcher reads it, with the aired rank this module's own walk produces."""
    numbering = recorded_numbering()
    ranks = {slot.episode_id: slot.sequence for slot in aired_slots(numbering)}
    dates = {
        an_episode_id(episode["id"]): episode["air_date"]
        for season in RECORDED_SEASONS
        for episode in recorded_episodes(season)
    }
    return tuple(
        StoredEpisode(
            episode_id=episode_id,
            air_date=date.fromisoformat(dates[episode_id]) if dates[episode_id] else None,
            aired_rank=ranks.get(episode_id),
        )
        for episode_id, _, _ in numbering
    )


def recorded_walk(season_type: str) -> tuple[TvdbEpisode, ...]:
    """Every recorded page of one ordering, concatenated exactly as the client's walk would return them."""
    return tuple(
        TvdbEpisode.model_validate(episode)
        for stem in RECORDED_ORDERINGS[season_type]
        for episode in recorded_page_episodes(stem)
    )


async def a_title_with_no_provider_ids(session: AsyncSession) -> Title:
    """A hand-entered work: a first-class record here, with no TheTVDB id and no episodes."""
    title = Title(media_type=MediaType.TV, tmdb_id=None, name="A Show Nobody Catalogued", match_key="a show")
    session.add(title)
    await session.flush()
    return title


def write_statements(statements: Sequence[str]) -> set[str]:
    """The distinct statements that changed something. A read is not a write, and a batched write is one."""
    return {
        statement.lower().lstrip()
        for statement in statements
        if statement.lower().lstrip().startswith(("insert", "update", "delete"))
    }


@pytest.fixture
def order_statements(engine: AsyncEngine) -> Iterator[list[str]]:
    with counted_statements(engine, "episode_order") as seen:
        yield seen


async def rows_for(session: AsyncSession, order_type: str, label: str = "") -> list[EpisodeOrder]:
    return list(
        await session.scalars(
            select(EpisodeOrder)
            .where(EpisodeOrder.order_type == order_type, EpisodeOrder.label == label)
            .order_by(EpisodeOrder.sequence)
        )
    )


async def laboon(session: AsyncSession) -> Episode:
    episode = await session.scalar(select(Episode).where(Episode.tmdb_episode_id == LABOON_TMDB_EPISODE_ID))
    assert episode is not None
    return episode


# -- the pure half ----------------------------------------------------------------------------------


def test_ranked_is_dense_and_one_based_even_when_the_numbering_has_gaps() -> None:
    slots = ranked(a_numbering((1, 4), (1, 9), (2, 20)))

    assert [slot.sequence for slot in slots] == [1, 2, 3]
    assert [(slot.order_season_number, slot.order_episode_number) for slot in slots] == [(1, 4), (1, 9), (2, 20)]


def test_ranked_walks_seasons_ascending_whatever_order_it_was_handed() -> None:
    slots = ranked(a_numbering((2, 62), (1, 1), (1, 61)))

    assert [(slot.order_season_number, slot.order_episode_number) for slot in slots] == [(1, 1), (1, 61), (2, 62)]


def test_aired_slots_exclude_season_zero() -> None:
    numbering = a_numbering((0, 1), (0, 2), (1, 1), (1, 2))

    slots = aired_slots(numbering)

    assert [slot.episode_id for slot in slots] == [numbering[2][0], numbering[3][0]]
    assert [slot.sequence for slot in slots] == [1, 2]


def test_specials_slots_are_season_zero_alone_ranked_from_one() -> None:
    numbering = a_numbering((0, 3), (0, 7), (1, 1))

    slots = specials_slots(numbering)

    assert [slot.sequence for slot in slots] == [1, 2]
    assert [slot.order_episode_number for slot in slots] == [3, 7]


def test_every_episode_lands_in_exactly_one_of_the_two_tmdb_orderings() -> None:
    numbering = a_numbering((0, 1), (1, 1), (1, 2), (2, 3))

    aired = aired_slots(numbering)
    specials = specials_slots(numbering)

    assert {slot.episode_id for slot in aired} | {slot.episode_id for slot in specials} == {
        triple[0] for triple in numbering
    }
    assert not {slot.episode_id for slot in aired} & {slot.episode_id for slot in specials}


def test_provider_slots_rank_only_the_episodes_that_were_paired() -> None:
    episodes = (
        a_tvdb_episode(10, season=1, number=1),
        a_tvdb_episode(11, season=1, number=2),
        a_tvdb_episode(12, season=1, number=3),
    )

    slots = provider_slots(episodes, {10: an_id(1), 12: an_id(3)})

    assert slots == (
        OrderSlot(episode_id=an_id(1), sequence=1, order_season_number=1, order_episode_number=1),
        OrderSlot(episode_id=an_id(3), sequence=2, order_season_number=1, order_episode_number=3),
    )


def test_provider_slots_rank_by_the_orderings_own_pair_not_by_the_order_it_arrived_in() -> None:
    episodes = (a_tvdb_episode(10, season=2, number=1), a_tvdb_episode(11, season=1, number=9))

    slots = provider_slots(episodes, {10: an_id(1), 11: an_id(2)})

    assert [slot.episode_id for slot in slots] == [an_id(2), an_id(1)]
    assert [slot.sequence for slot in slots] == [1, 2]


def test_repeated_provider_ids_names_what_a_looped_walk_read_twice() -> None:
    episodes = (a_tvdb_episode(10, season=1, number=1), a_tvdb_episode(10, season=1, number=1))

    assert repeated_provider_ids(episodes) == (10,)


def test_repeated_provider_ids_is_empty_for_a_walk_that_ended_where_it_should() -> None:
    assert repeated_provider_ids((a_tvdb_episode(10, season=1, number=1),)) == ()


@pytest.mark.parametrize("season_type", sorted(entry["type"] for entry in fixture_json(TVDB, "seasons_types")["data"]))
def test_provider_order_type_keeps_the_name_the_runtime_list_gave(season_type: str) -> None:
    assert provider_order_type(season_type) == season_type


def test_the_default_path_is_an_alias_and_is_never_stored_as_a_type_of_its_own() -> None:
    # `default` is accepted as an episodes-endpoint path and answered exactly what the service's own
    # aired ordering answered (measured 2026-09-15), so storing it would duplicate a whole ordering
    # under a second name (CLAUDE.md section 2.1, item 6). It is not in the runtime list either.
    assert provider_order_type("default") is None
    assert "alias" in str(refusal_for("default"))
    assert "default" not in {entry["type"] for entry in fixture_json(TVDB, "seasons_types")["data"]}


def test_every_refusal_says_which_one_it_was() -> None:
    reasons = {
        refusal_for(""),
        refusal_for("t" * (ORDER_TYPE_LENGTH + 1)),
        refusal_for("default"),
        refusal_for(AIRED_ORDER_TYPE),
    }

    assert None not in reasons
    assert len(reasons) == 4
    assert refusal_for(THEIR_ABSOLUTE) is None


def test_a_type_name_this_app_computes_itself_is_refused_rather_than_written() -> None:
    # The aired rank is this app's own, computed from TMDB and carrying `source=tmdb`. A provider
    # ordering of that name would collide with it on the deferred unique and lie about its source.
    assert provider_order_type(AIRED_ORDER_TYPE) is None


def test_a_blank_or_oversized_type_name_is_refused_before_it_can_truncate_a_column() -> None:
    # `order_type` is String(n); a longer name would abort the whole transaction on insert, and two
    # names clipped to fit would become one ordering.
    assert provider_order_type("") is None
    assert provider_order_type("t" * (ORDER_TYPE_LENGTH + 1)) is None
    assert provider_order_type("t" * ORDER_TYPE_LENGTH) == "t" * ORDER_TYPE_LENGTH


def test_order_values_carry_the_rank_and_the_pair_the_ui_prints() -> None:
    slot = OrderSlot(episode_id=an_id(1), sequence=62, order_season_number=2, order_episode_number=1)

    values = order_values(an_id(9), THEIR_DISC, NO_LABEL, ExternalSource.TVDB, slot)

    assert values == {
        "title_id": an_id(9),
        "episode_id": an_id(1),
        "order_type": THEIR_DISC,
        "label": NO_LABEL,
        "sequence": 62,
        "order_season_number": 2,
        "order_episode_number": 1,
        "source": ExternalSource.TVDB,
    }


def test_comparable_row_is_the_four_columns_a_stored_row_is_compared_on() -> None:
    slot = OrderSlot(episode_id=an_id(1), sequence=3, order_season_number=1, order_episode_number=4)

    assert comparable_row(ExternalSource.TMDB, slot) == (3, 1, 4, ExternalSource.TMDB)


def test_a_title_is_named_by_its_tmdb_pointer_and_falls_back_to_its_own_id() -> None:
    matched = Title(id=an_id(1), media_type=MediaType.TV, tmdb_id=ONE_PIECE)
    hand_entered = Title(id=an_id(2), media_type=MediaType.TV, tmdb_id=None)

    assert resource_label(matched) == f"tv:{ONE_PIECE}"
    assert resource_label(hand_entered) == str(an_id(2))


def test_summed_folds_every_orderings_result_into_one() -> None:
    folded = summed(
        {
            THEIR_ABSOLUTE: IngestOutcome(inserted=77, outcome="fresh"),
            THEIR_DISC: IngestOutcome(skipped=1, outcome="failed"),
        }
    )

    assert folded == IngestOutcome(inserted=77, skipped=1, outcome="failed")
    assert summed({}) == IngestOutcome()


def test_episodes_key_names_the_series_and_the_ordering() -> None:
    assert episodes_key(ONE_PIECE_TVDB, THEIR_ABSOLUTE) == f"{ONE_PIECE_TVDB}/{THEIR_ABSOLUTE}"


@pytest.mark.parametrize("literal", FORBIDDEN_LITERALS)
def test_no_season_type_name_appears_in_the_ingests_own_source(literal: str) -> None:
    # The list is read at runtime from `GET /v4/seasons/types`; a name in the code would be a list this
    # app had decided for itself, and an eighth type would then be unstorable.
    for module in ("episode_orders", "tvdb_matching"):
        source = Path(f"src/tv_watchlist/ingest/{module}.py").read_text()
        assert literal not in source


def test_the_specials_bucket_is_its_own_ordering_not_the_aired_one() -> None:
    assert SPECIALS_ORDER_TYPE != AIRED_ORDER_TYPE
    assert SPECIALS_ORDER_LABEL != ""


def test_the_upsert_re_ranks_in_place_on_the_one_row_per_episode_key() -> None:
    compiled = str(EpisodeOrderIngest.upsert_shape().compile(dialect=postgresql.dialect()))

    assert "ON CONFLICT (episode_id, order_type, label) DO UPDATE" in compiled
    assert "sequence = excluded.sequence" in compiled
    # The conflict key itself is never rewritten: that would be a no-op churning `updated_at`.
    assert "episode_id = excluded.episode_id" not in compiled


# -- the reference numbers the half that writes asserts, computed here without a database ------------


def test_the_aired_walk_over_the_recorded_slice_puts_laboon_at_sixty_two() -> None:
    slots = aired_slots(recorded_numbering())

    laboon_slot = next(slot for slot in slots if slot.episode_id == an_episode_id(LABOON_TMDB_EPISODE_ID))
    assert len(slots) == REGULAR_EPISODES
    assert laboon_slot.sequence == LABOON_AIRED_SEQUENCE
    assert (laboon_slot.order_season_number, laboon_slot.order_episode_number) == LABOON_TMDB_PAIR


def test_the_specials_walk_over_the_recorded_slice_keeps_every_special() -> None:
    slots = specials_slots(recorded_numbering())

    assert len(slots) == SPECIALS
    assert [slot.sequence for slot in slots] == list(range(1, SPECIALS + 1))


@pytest.mark.parametrize(("season_type", "expected"), sorted(WRITTEN_ROWS.items()))
def test_each_recorded_ordering_ranks_the_rows_the_database_half_expects(season_type: str, expected: int) -> None:
    walk = recorded_walk(season_type)

    slots = provider_slots(walk, match_tvdb_episodes(walk, recorded_stored_episodes()).matched)

    assert len(slots) == expected
    assert [slot.sequence for slot in slots] == list(range(1, expected + 1))


@pytest.mark.parametrize(("season_type", "expected"), sorted(LABOON_IN.items()))
def test_each_recorded_ordering_places_laboon_where_the_database_half_expects(
    season_type: str, expected: tuple[int, int, int]
) -> None:
    walk = recorded_walk(season_type)

    slots = provider_slots(walk, match_tvdb_episodes(walk, recorded_stored_episodes()).matched)

    slot = next(slot for slot in slots if slot.episode_id == an_episode_id(LABOON_TMDB_EPISODE_ID))
    assert (slot.sequence, slot.order_season_number, slot.order_episode_number) == expected


def test_the_recorded_walk_of_the_second_page_alone_pairs_with_nothing() -> None:
    # What the "prunes nothing" case rests on: page 1's absolute numbers start at 501, past everything
    # the recorded TMDB slice holds.
    walk = recorded_walk(THEIR_ABSOLUTE)[-1:]

    assert match_tvdb_episodes(walk, recorded_stored_episodes()).matched == {}


def test_a_repeated_page_is_what_the_loop_detector_sees() -> None:
    page = recorded_walk(THEIR_AIRED)

    assert repeated_provider_ids(page + page) == tuple(episode.id for episode in page)


# -- the half that writes ---------------------------------------------------------------------------


async def test_the_aired_rank_walks_seasons_ascending_and_excludes_season_zero(db_session: AsyncSession) -> None:
    title = await seeded_one_piece(db_session)
    ingest, _ = order_ingest(db_session)

    outcome = await ingest.rank_aired(title)
    await db_session.flush()

    aired = await rows_for(db_session, AIRED_ORDER_TYPE)
    specials = await rows_for(db_session, SPECIALS_ORDER_TYPE, SPECIALS_ORDER_LABEL)
    assert outcome.inserted == REGULAR_EPISODES + SPECIALS
    assert [row.sequence for row in aired] == list(range(1, REGULAR_EPISODES + 1))
    assert [row.sequence for row in specials] == list(range(1, SPECIALS + 1))
    assert {row.order_season_number for row in specials} == {0}
    assert 0 not in {row.order_season_number for row in aired}


async def test_laboons_aired_rank_is_sixty_two_and_carries_the_tmdb_pair(db_session: AsyncSession) -> None:
    title = await seeded_one_piece(db_session)
    ingest, _ = order_ingest(db_session)

    await ingest.rank_aired(title)
    await db_session.flush()

    episode = await laboon(db_session)
    row = await db_session.scalar(
        select(EpisodeOrder).where(EpisodeOrder.episode_id == episode.id, EpisodeOrder.order_type == AIRED_ORDER_TYPE)
    )
    assert row is not None
    assert row.sequence == LABOON_AIRED_SEQUENCE
    assert (row.order_season_number, row.order_episode_number) == LABOON_TMDB_PAIR
    assert row.source is ExternalSource.TMDB


async def test_laboon_carries_four_numberings_that_agree_on_one_episode_id(db_session: AsyncSession) -> None:
    title = await seeded_one_piece(db_session)
    ingest, _ = order_ingest(db_session)

    await ingest.rank_aired(title)
    await ingest.ingest_tvdb_orders(title)
    await db_session.flush()

    episode = await laboon(db_session)
    rows = {
        row.order_type: row
        for row in await db_session.scalars(select(EpisodeOrder).where(EpisodeOrder.episode_id == episode.id))
    }
    assert set(rows) == {AIRED_ORDER_TYPE, *LABOON_IN}
    assert (rows[AIRED_ORDER_TYPE].sequence, rows[AIRED_ORDER_TYPE].source) == (
        LABOON_AIRED_SEQUENCE,
        ExternalSource.TMDB,
    )
    for order_type, expected in LABOON_IN.items():
        row = rows[order_type]
        assert (row.sequence, row.order_season_number, row.order_episode_number) == expected
        assert row.source is ExternalSource.TVDB


async def test_source_says_which_provider_produced_each_ordering(db_session: AsyncSession) -> None:
    title = await seeded_one_piece(db_session)
    ingest, _ = order_ingest(db_session)

    await ingest.rank_aired(title)
    await ingest.ingest_tvdb_orders(title)
    await db_session.flush()

    by_source: dict[ExternalSource, set[str]] = {}
    for row in await db_session.scalars(select(EpisodeOrder)):
        by_source.setdefault(row.source, set()).add(row.order_type)
    assert by_source[ExternalSource.TMDB] == {AIRED_ORDER_TYPE, SPECIALS_ORDER_TYPE}
    assert by_source[ExternalSource.TVDB] == set(LABOON_IN)


async def test_every_recorded_ordering_writes_the_rows_it_paired(db_session: AsyncSession) -> None:
    title = await seeded_one_piece(db_session)
    ingest, _ = order_ingest(db_session)

    outcomes = await ingest.ingest_tvdb_orders(title)
    await db_session.flush()

    for order_type, expected in WRITTEN_ROWS.items():
        assert len(await rows_for(db_session, order_type)) == expected
        assert outcomes[order_type].inserted == expected


async def test_the_tvdb_series_id_comes_from_the_external_id_row_never_from_a_search(
    db_session: AsyncSession,
) -> None:
    title = await seeded_one_piece(db_session)
    ingest, routes = order_ingest(db_session)

    series_id = await tvdb_series_id_for(db_session, title)
    await ingest.ingest_tvdb_orders(title)

    assert series_id == ONE_PIECE_TVDB
    assert [url for url in routes.requested if "/search" in url] == []


async def test_an_unknown_episodes_result_writes_nothing_and_records_last_error(db_session: AsyncSession) -> None:
    title = await seeded_one_piece(db_session)
    ingest, _ = order_ingest(db_session)

    outcomes = await ingest.ingest_tvdb_orders(title)
    await db_session.flush()

    unknown = sorted(set(outcomes) - set(RECORDED_ORDERINGS))
    assert unknown
    for order_type in unknown:
        assert await rows_for(db_session, order_type) == []
        assert outcomes[order_type].outcome == "failed"
        cursor = await db_session.scalar(
            select(SyncState).where(
                SyncState.source == ExternalSource.TVDB,
                SyncState.resource_type == SyncResourceType.TVDB_EPISODES,
                SyncState.resource_key == episodes_key(ONE_PIECE_TVDB, order_type),
            )
        )
        assert cursor is not None
        assert cursor.last_error
        assert cursor.consecutive_failures == 1
    assert len(await rows_for(db_session, THEIR_ABSOLUTE)) == WRITTEN_ROWS[THEIR_ABSOLUTE]
    # An ordering that came back unknown is recorded, never substituted: the aired rank is this app's
    # own and nothing about a provider refusal may write into it (CLAUDE.md section 18.2, rule 2).
    assert await rows_for(db_session, AIRED_ORDER_TYPE) == []


async def test_a_type_the_app_has_never_seen_is_stored_and_ignored(db_session: AsyncSession) -> None:
    title = await seeded_one_piece(db_session)
    ingest, _ = order_ingest(
        db_session,
        orderings={A_TYPE_THE_APP_HAS_NEVER_SEEN: RECORDED_ORDERINGS[THEIR_AIRED]},
        season_types=(A_TYPE_THE_APP_HAS_NEVER_SEEN,),
    )

    outcomes = await ingest.ingest_tvdb_orders(title)
    await db_session.flush()

    assert set(outcomes) == {A_TYPE_THE_APP_HAS_NEVER_SEEN}
    rows = await rows_for(db_session, A_TYPE_THE_APP_HAS_NEVER_SEEN)
    assert len(rows) == WRITTEN_ROWS[THEIR_AIRED]
    assert {row.source for row in rows} == {ExternalSource.TVDB}


async def test_a_looped_walk_writes_nothing_and_records_last_error(db_session: AsyncSession) -> None:
    title = await seeded_one_piece(db_session)
    # The same recorded page served twice: the shape a walk takes when the provider's `next` points back
    # at a page already read, and the only truncation this client's walk can produce.
    ingest, _ = order_ingest(
        db_session,
        orderings={THEIR_ABSOLUTE: RECORDED_ORDERINGS[THEIR_ABSOLUTE][:1] * 2},
        season_types=(THEIR_ABSOLUTE,),
    )

    outcomes = await ingest.ingest_tvdb_orders(title)
    await db_session.flush()

    assert await rows_for(db_session, THEIR_ABSOLUTE) == []
    assert outcomes[THEIR_ABSOLUTE].outcome == "failed"


async def test_an_ordering_that_pairs_with_nothing_writes_nothing_and_prunes_nothing(
    db_session: AsyncSession,
) -> None:
    title = await seeded_one_piece(db_session)
    first, _ = order_ingest(db_session, orderings={THEIR_ABSOLUTE: RECORDED_ORDERINGS[THEIR_ABSOLUTE]})
    await first.ingest_tvdb_orders(title)
    await db_session.flush()
    # The second page alone pairs with nothing this projection holds: its absolute numbers start at 501.
    second, _ = order_ingest(
        db_session,
        orderings={THEIR_ABSOLUTE: RECORDED_ORDERINGS[THEIR_ABSOLUTE][1:]},
        season_types=(THEIR_ABSOLUTE,),
    )

    await second.ingest_tvdb_orders(title)
    await db_session.flush()

    assert len(await rows_for(db_session, THEIR_ABSOLUTE)) == WRITTEN_ROWS[THEIR_ABSOLUTE]


async def test_a_second_rank_pass_writes_nothing_at_all(db_session: AsyncSession, order_statements: list[str]) -> None:
    title = await seeded_one_piece(db_session)
    ingest, _ = order_ingest(db_session)
    await ingest.rank_aired(title)
    await db_session.flush()
    order_statements.clear()

    outcome = await ingest.rank_aired(title)
    await db_session.flush()

    assert outcome.inserted == 0
    assert outcome.updated == 0
    assert outcome.unchanged == REGULAR_EPISODES + SPECIALS
    assert write_statements(order_statements) == set()


async def test_reranking_after_an_inserted_episode_is_one_statement_under_the_deferred_unique(
    db_session: AsyncSession, order_statements: list[str]
) -> None:
    title = await seeded_one_piece(db_session)
    ingest, _ = order_ingest(db_session)
    await ingest.rank_aired(title)
    await db_session.flush()
    season = await db_session.scalar(select(Season).where(Season.title_id == title.id, Season.season_number == 1))
    assert season is not None
    db_session.add(
        Episode(
            title_id=title.id,
            season_id=season.id,
            season_number=1,
            episode_number=AN_EPISODE_NUMBER_NO_RECORDED_SEASON_USES,
            tmdb_episode_id=A_TMDB_EPISODE_ID_NO_FIXTURE_USES,
        )
    )
    await db_session.flush()
    order_statements.clear()

    outcome = await ingest.rank_aired(title)
    await db_session.flush()

    episode = await laboon(db_session)
    moved = await db_session.scalar(
        select(EpisodeOrder.sequence).where(
            EpisodeOrder.episode_id == episode.id, EpisodeOrder.order_type == AIRED_ORDER_TYPE
        )
    )
    assert moved == LABOON_AIRED_SEQUENCE + 1
    assert outcome.inserted == 1
    # One statement for the whole numbering: the new episode and the sixteen it pushed along, inserts
    # and re-ranks together, under the deferred unique.
    writes = write_statements(order_statements)
    assert len(writes) == 1
    assert next(iter(writes)).startswith("insert into episode_order")
    # The unique on (title_id, order_type, label, sequence) is DEFERRABLE INITIALLY DEFERRED, so a flush
    # proves nothing about it; this is what makes the database check the shift the re-rank just made.
    await db_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


async def test_a_season_type_named_after_this_apps_own_ordering_is_refused_and_recorded(
    db_session: AsyncSession,
) -> None:
    title = await seeded_one_piece(db_session)
    # A provider ordering written under the aired rank's name would collide with it on the deferred
    # unique and claim `source=tvdb` for a rank TMDB produced.
    ingest, routes = order_ingest(db_session, season_types=(AIRED_ORDER_TYPE,))

    outcomes = await ingest.ingest_tvdb_orders(title)
    await db_session.flush()

    assert outcomes[AIRED_ORDER_TYPE].outcome == "failed"
    assert await rows_for(db_session, AIRED_ORDER_TYPE) == []
    assert [url for url in routes.requested if "/episodes/" in url] == []


async def test_a_backoff_that_has_not_run_out_stops_the_walk_before_a_request(db_session: AsyncSession) -> None:
    title = await seeded_one_piece(db_session)
    await PostgresResponseCache(db_session).record_failure(
        ExternalSource.TVDB.value,
        SyncResourceType.TVDB_EPISODES.value,
        episodes_key(ONE_PIECE_TVDB, THEIR_ABSOLUTE),
        "an earlier pass could not read this ordering",
    )
    ingest, routes = order_ingest(db_session, season_types=(THEIR_ABSOLUTE,))

    outcomes = await ingest.ingest_tvdb_orders(title)
    await db_session.flush()

    assert outcomes[THEIR_ABSOLUTE] == IngestOutcome(skipped=1, outcome="throttled")
    assert await rows_for(db_session, THEIR_ABSOLUTE) == []
    assert [url for url in routes.requested if "/episodes/" in url] == []


async def test_a_title_with_no_tvdb_id_asks_for_no_ordering_at_all(db_session: AsyncSession) -> None:
    title = await a_title_with_no_provider_ids(db_session)
    ingest, routes = order_ingest(db_session)

    outcomes = await ingest.ingest_tvdb_orders(title)

    assert outcomes == {}
    assert await tvdb_series_id_for(db_session, title) is None
    assert routes.requested == []


async def test_an_unconfigured_thetvdb_is_a_disabled_feature_not_a_failure(db_session: AsyncSession) -> None:
    title = await seeded_one_piece(db_session)
    ingest, routes = order_ingest(db_session, configured=False)

    outcomes = await ingest.ingest_tvdb_orders(title)

    assert outcomes == {}
    assert routes.requested == []


async def test_a_provider_refusal_writes_nothing_and_records_why(db_session: AsyncSession) -> None:
    title = await seeded_one_piece(db_session)
    ingest, _ = order_ingest(db_session, season_types=(THEIR_ABSOLUTE,), episode_status=500)

    outcomes = await ingest.ingest_tvdb_orders(title)
    await db_session.flush()

    assert outcomes[THEIR_ABSOLUTE].outcome == "failed"
    assert await rows_for(db_session, THEIR_ABSOLUTE) == []
    cursor = await db_session.scalar(
        select(SyncState).where(
            SyncState.source == ExternalSource.TVDB,
            SyncState.resource_type == SyncResourceType.TVDB_EPISODES,
            SyncState.resource_key == episodes_key(ONE_PIECE_TVDB, THEIR_ABSOLUTE),
        )
    )
    assert cursor is not None
    assert cursor.last_error


async def test_a_title_with_no_episodes_ranks_nothing_and_says_so(
    db_session: AsyncSession, order_statements: list[str]
) -> None:
    title = await a_title_with_no_provider_ids(db_session)
    ingest, _ = order_ingest(db_session)
    order_statements.clear()

    outcome = await ingest.rank_aired(title)
    await db_session.flush()

    assert outcome == IngestOutcome(outcome="not-modified")
    assert write_statements(order_statements) == set()


async def test_an_episode_that_left_an_ordering_is_pruned_from_it(db_session: AsyncSession) -> None:
    title = await seeded_one_piece(db_session)
    both_pages, _ = order_ingest(db_session, season_types=(THEIR_DISC,))
    await both_pages.ingest_tvdb_orders(title)
    await db_session.flush()
    before = await rows_for(db_session, THEIR_DISC)
    # The same ordering as the service now has it: one page shorter, so the special its second page
    # carried is no longer part of it.
    shorter, _ = order_ingest(
        db_session,
        orderings={THEIR_DISC: RECORDED_ORDERINGS[THEIR_DISC][:1]},
        season_types=(THEIR_DISC,),
    )

    outcomes = await shorter.ingest_tvdb_orders(title)
    await db_session.flush()

    after = await rows_for(db_session, THEIR_DISC)
    assert len(before) == WRITTEN_ROWS[THEIR_DISC]
    assert len(after) == WRITTEN_ROWS[THEIR_DISC] - 1
    assert outcomes[THEIR_DISC].unchanged == len(after)
    assert {row.episode_id for row in after} < {row.episode_id for row in before}


async def test_a_walk_shorter_than_the_service_says_writes_nothing_and_records_last_error(
    db_session: AsyncSession,
) -> None:
    title = await seeded_one_piece(db_session)
    first, _ = order_ingest(db_session, season_types=(THEIR_ABSOLUTE,))
    await first.ingest_tvdb_orders(title)
    await db_session.flush()
    standing = await rows_for(db_session, THEIR_ABSOLUTE)
    # The same pages, now claiming the ordering holds one more episode than they carry: the shape a walk
    # takes when a page never arrived. Writing it would prune every row that page held.
    short, _ = order_ingest(db_session, season_types=(THEIR_ABSOLUTE,), overstate_by=1)

    outcomes = await short.ingest_tvdb_orders(title)
    await db_session.flush()

    assert outcomes[THEIR_ABSOLUTE].outcome == "failed"
    assert len(await rows_for(db_session, THEIR_ABSOLUTE)) == len(standing)
    cursor = await db_session.scalar(
        select(SyncState).where(
            SyncState.source == ExternalSource.TVDB,
            SyncState.resource_type == SyncResourceType.TVDB_EPISODES,
            SyncState.resource_key == episodes_key(ONE_PIECE_TVDB, THEIR_ABSOLUTE),
        )
    )
    assert cursor is not None
    assert "of the" in str(cursor.last_error)


async def test_the_default_alias_is_refused_before_a_request_is_built(db_session: AsyncSession) -> None:
    title = await seeded_one_piece(db_session)
    ingest, routes = order_ingest(db_session, season_types=("default",))

    outcomes = await ingest.ingest_tvdb_orders(title)
    await db_session.flush()

    assert outcomes["default"].outcome == "failed"
    assert await rows_for(db_session, "default") == []
    assert [url for url in routes.requested if "/episodes/" in url] == []
