"""phase 1 schema

Revision ID: 0001
Revises:
Create Date: 2026-09-20 16:57:31.732921

"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen here on purpose, never imported from data/enums.py: a later member gets its own revision rather
# than silently rewriting what this one already ran against a live database.
ENUMS: Final[dict[str, tuple[str, ...]]] = {
    "media_type": ("movie", "tv"),
    "unit_kind": ("movie", "episodes", "season", "series", "special", "unknown"),
    "resolution_state": ("unresolved", "auto", "confirmed", "rejected"),
    "entity_kind": ("title", "season", "episode"),
    "external_source": ("tmdb", "tvdb", "imdb", "wikidata"),
    "artwork_kind": ("poster", "backdrop", "logo", "still"),
    "watch_event_kind": ("started", "progressed", "completed", "skipped", "unset"),
    "watch_event_source": ("ui", "excel_mirror", "player"),
    "watch_subject_kind": ("episode", "title", "curated_entry"),
    "sync_resource_type": (
        "tmdb_configuration",
        "tmdb_movie",
        "tmdb_tv",
        "tmdb_season",
        "tmdb_external_ids",
        "tmdb_alternative_titles",
        "tmdb_changes",
        "tvdb_season_types",
        "tvdb_episodes",
        "tvdb_updates",
    ),
}

# Every statement below is executed on its own. SQLAlchemy's asyncpg dialect prepares each string it is
# handed, and the extended query protocol rejects a string holding two commands, so a function and its
# trigger cannot travel together even though psql would accept them in one go.
WATCH_EVENT_FUNCTION: Final[str] = """
CREATE OR REPLACE FUNCTION watch_event_reject_mutation() RETURNS trigger
LANGUAGE plpgsql AS $fn$
BEGIN
    RAISE EXCEPTION 'watch_event is append-only (attempted %)', TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$fn$
"""

WATCH_EVENT_TRIGGER: Final[str] = """
CREATE TRIGGER watch_event_no_mutation
    BEFORE UPDATE OR DELETE ON watch_event
    FOR EACH ROW EXECUTE FUNCTION watch_event_reject_mutation()
"""

# The tie-break chain is all three keys: occurred_at is client-supplied and can arrive late, recorded_at is
# server-assigned, and id is what makes two identically stamped events resolve the same way every time.
EPISODE_WATCH_STATE: Final[str] = """
CREATE VIEW episode_watch_state AS
SELECT DISTINCT ON (e.episode_id)
       e.episode_id,
       e.kind,
       e.position_seconds,
       e.runtime_seconds,
       e.occurred_at,
       e.recorded_at,
       e.category_id,
       e.id AS watch_event_id
  FROM watch_event AS e
 WHERE e.episode_id IS NOT NULL
 ORDER BY e.episode_id, e.occurred_at DESC, e.recorded_at DESC, e.id DESC
"""

# Precedence: an entry-level event at or after the latest unit-level event wins; otherwise the roll-up.
# completed + skipped = total counts as completed - the same semantics as WatchCounts.trackable, so the
# two progress readouts in the app cannot disagree about one category.
CURATED_ENTRY_WATCH_STATE: Final[str] = """
CREATE VIEW curated_entry_watch_state AS
WITH entry_events AS (
    SELECT DISTINCT ON (e.curated_entry_id)
           e.curated_entry_id, e.kind, e.occurred_at
      FROM watch_event AS e
     WHERE e.subject_kind = 'curated_entry' AND e.curated_entry_id IS NOT NULL
     ORDER BY e.curated_entry_id, e.occurred_at DESC, e.recorded_at DESC, e.id DESC
),
title_states AS (
    SELECT DISTINCT ON (e.title_id)
           e.title_id, e.kind, e.occurred_at
      FROM watch_event AS e
     WHERE e.subject_kind = 'title' AND e.title_id IS NOT NULL
     ORDER BY e.title_id, e.occurred_at DESC, e.recorded_at DESC, e.id DESC
),
unit_states AS (
    SELECT i.curated_entry_id,
           COALESCE(s.kind, t.kind) AS kind,
           COALESCE(s.occurred_at, t.occurred_at) AS occurred_at
      FROM curated_entry_item AS i
      LEFT JOIN episode_watch_state AS s ON s.episode_id = i.episode_id
      LEFT JOIN title_states AS t ON t.title_id = i.movie_title_id
),
rollup AS (
    SELECT curated_entry_id,
           COUNT(*)                                                   AS episode_total,
           COUNT(*) FILTER (WHERE kind = 'completed')                 AS episode_completed,
           COUNT(*) FILTER (WHERE kind = 'skipped')                   AS episode_skipped,
           COUNT(*) FILTER (WHERE kind IN ('started', 'progressed'))  AS episode_started,
           MAX(occurred_at)                                           AS latest_unit_at
      FROM unit_states
     GROUP BY curated_entry_id
)
SELECT ce.id AS curated_entry_id,
       ce.category_id,
       CASE
         WHEN ee.kind IS NOT NULL AND (r.latest_unit_at IS NULL OR ee.occurred_at >= r.latest_unit_at) THEN ee.kind
         WHEN COALESCE(r.episode_total, 0) = 0 THEN 'unset'::watch_event_kind
         WHEN r.episode_skipped = r.episode_total THEN 'skipped'::watch_event_kind
         WHEN r.episode_completed + r.episode_skipped = r.episode_total THEN 'completed'::watch_event_kind
         WHEN r.episode_completed + r.episode_started > 0 THEN 'progressed'::watch_event_kind
         ELSE 'unset'::watch_event_kind
       END AS kind,
       COALESCE(r.episode_total, 0)::integer     AS episode_total,
       COALESCE(r.episode_completed, 0)::integer AS episode_completed,
       COALESCE(r.episode_skipped, 0)::integer   AS episode_skipped,
       COALESCE(r.episode_started, 0)::integer   AS episode_started,
       GREATEST(ee.occurred_at, r.latest_unit_at) AS as_of
  FROM curated_entry AS ce
  LEFT JOIN entry_events AS ee ON ee.curated_entry_id = ce.id
  LEFT JOIN rollup AS r ON r.curated_entry_id = ce.id
 WHERE ce.removed_at IS NULL
"""

TABLES_IN_DEPENDENCY_ORDER: Final[tuple[str, ...]] = (
    "category",
    "title",
    "season",
    "episode",
    "episode_order",
    "external_id",
    "artwork",
    "curated_entry",
    "curated_entry_item",
    "watch_event",
    "sync_state",
)


def _enum(name: str) -> postgresql.ENUM:
    """The type as a column reference only; upgrade() creates each one once, by hand."""
    return postgresql.ENUM(*ENUMS[name], name=name, create_type=False)


def _uuid_pk() -> sa.Column[sa.Uuid]:
    """Minted client-side too, so the reconciler knows a row's id before flush and can write it to the sheet."""
    return sa.Column("id", sa.Uuid(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()"))


def _pk(table: str) -> sa.PrimaryKeyConstraint:
    return sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}"))


def _timestamps() -> list[sa.Column[sa.DateTime]]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def _fk(table: str, column: str, target: str, ondelete: str, *, nullable: bool = False) -> sa.Column[sa.Uuid]:
    """A typed foreign key carrying the name the metadata's naming convention would mint for it.

    Spelled out here rather than read from NAMING_CONVENTION on purpose: a merged revision is frozen, and
    it must keep emitting the names it already emitted against live databases even if the convention is
    changed later. A convention change therefore turns the models/revision parity test red on the names -
    correctly, and not because of a bug in this file. The fix is a new revision that renames, never an edit
    to this one.
    """
    referred = target.split(".", 1)[0]
    return sa.Column(
        column,
        sa.Uuid(as_uuid=True),
        sa.ForeignKey(target, ondelete=ondelete, name=op.f(f"fk_{table}_{column}_{referred}")),
        nullable=nullable,
    )


def _create_type(name: str, labels: tuple[str, ...]) -> str:
    """CREATE TYPE takes no bind parameters; every label here is a literal declared a few lines above."""
    members = ", ".join(f"'{label}'" for label in labels)
    return f"CREATE TYPE {name} AS ENUM ({members})"


def _category() -> None:
    op.create_table(
        "category",
        sa.Column("slug", sa.String(200), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("sheet_title", sa.String(255), nullable=False),
        sa.Column("accent", sa.String(7), nullable=False),
        sa.Column("identity_column_key", sa.String(120)),
        # The same st_mtime float the live API already carries; re-typing it here would fork a contract.
        sa.Column("workbook_mtime", sa.Float),
        sa.Column("workbook_digest", sa.String(64)),
        sa.Column("last_ingested_at", sa.DateTime(timezone=True)),
        sa.Column("last_mirrored_at", sa.DateTime(timezone=True)),
        sa.Column("last_ingest_error", sa.Text),
        sa.Column("retired_at", sa.DateTime(timezone=True)),
        _uuid_pk(),
        *_timestamps(),
        _pk("category"),
        sa.CheckConstraint("accent ~ '^#[0-9A-Fa-f]{6}$'", name=op.f("ck_category_accent_hex")),
        sa.UniqueConstraint("slug", name=op.f("uq_category_slug")),
    )


def _title() -> None:
    op.create_table(
        "title",
        sa.Column("media_type", _enum("media_type"), nullable=False),
        # Nullable: a hand-entered local title with no provider match is a first-class record, and Postgres
        # treats NULLs as distinct so uq(media_type, tmdb_id) still holds.
        sa.Column("tmdb_id", sa.Integer),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("original_name", sa.String(500)),
        sa.Column("match_key", sa.String(255), nullable=False),
        sa.Column("overview", sa.Text),
        sa.Column("first_air_date", sa.Date),
        sa.Column("last_air_date", sa.Date),
        sa.Column("runtime_seconds", sa.Integer),
        sa.Column("episode_count", sa.Integer),
        sa.Column("season_count", sa.Integer),
        sa.Column("status", sa.String(60)),
        sa.Column("original_language", sa.String(16)),
        _uuid_pk(),
        *_timestamps(),
        _pk("title"),
        sa.UniqueConstraint("media_type", "tmdb_id", name=op.f("uq_title_media_type_tmdb_id")),
        sa.CheckConstraint(
            "runtime_seconds IS NULL OR runtime_seconds > 0", name=op.f("ck_title_runtime_seconds_positive")
        ),
        sa.CheckConstraint(
            "episode_count IS NULL OR episode_count >= 0", name=op.f("ck_title_episode_count_non_negative")
        ),
        sa.CheckConstraint(
            "season_count IS NULL OR season_count >= 0", name=op.f("ck_title_season_count_non_negative")
        ),
    )
    op.create_index(
        op.f("ix_title_name_trgm"), "title", ["name"], postgresql_using="gin", postgresql_ops={"name": "gin_trgm_ops"}
    )
    op.create_index(op.f("ix_title_match_key"), "title", ["match_key"])


def _season() -> None:
    op.create_table(
        "season",
        _fk("season", "title_id", "title.id", "CASCADE"),
        sa.Column("season_number", sa.Integer, nullable=False),
        sa.Column("name", sa.String(500)),
        sa.Column("overview", sa.Text),
        sa.Column("air_date", sa.Date),
        sa.Column("episode_count", sa.Integer),
        _uuid_pk(),
        *_timestamps(),
        _pk("season"),
        sa.UniqueConstraint("title_id", "season_number", name=op.f("uq_season_title_id_season_number")),
        sa.CheckConstraint("season_number >= 0", name=op.f("ck_season_season_number_non_negative")),
        sa.CheckConstraint(
            "episode_count IS NULL OR episode_count >= 0", name=op.f("ck_season_episode_count_non_negative")
        ),
    )
    op.create_index(op.f("ix_season_title_id"), "season", ["title_id"])


def _episode() -> None:
    op.create_table(
        "episode",
        # Denormalised on purpose, so every order query stays a single join.
        _fk("episode", "title_id", "title.id", "CASCADE"),
        _fk("episode", "season_id", "season.id", "CASCADE"),
        sa.Column("season_number", sa.Integer, nullable=False),
        sa.Column("episode_number", sa.Integer, nullable=False),
        sa.Column("tmdb_episode_id", sa.Integer, nullable=False),
        sa.Column("name", sa.String(500)),
        sa.Column("overview", sa.Text),
        sa.Column("air_date", sa.Date),
        sa.Column("runtime_seconds", sa.Integer),
        sa.Column("production_code", sa.String(60)),
        _uuid_pk(),
        *_timestamps(),
        _pk("episode"),
        sa.UniqueConstraint("season_id", "episode_number", name=op.f("uq_episode_season_id_episode_number")),
        sa.UniqueConstraint("tmdb_episode_id", name=op.f("uq_episode_tmdb_episode_id")),
        sa.CheckConstraint("season_number >= 0", name=op.f("ck_episode_season_number_non_negative")),
        sa.CheckConstraint("episode_number >= 0", name=op.f("ck_episode_episode_number_non_negative")),
        sa.CheckConstraint(
            "runtime_seconds IS NULL OR runtime_seconds > 0", name=op.f("ck_episode_runtime_seconds_positive")
        ),
    )
    op.create_index(op.f("ix_episode_title_id"), "episode", ["title_id"])
    op.create_index(op.f("ix_episode_season_id"), "episode", ["season_id"])


def _episode_order() -> None:
    op.create_table(
        "episode_order",
        _fk("episode_order", "title_id", "title.id", "CASCADE"),
        _fk("episode_order", "episode_id", "episode.id", "CASCADE"),
        # An open string, never an enum: TheTVDB's season types are read at runtime and the set is not closed.
        sa.Column("order_type", sa.String(32), nullable=False),
        sa.Column("label", sa.String(120), server_default="", nullable=False),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("order_season_number", sa.Integer),
        sa.Column("order_episode_number", sa.Integer),
        sa.Column("source", _enum("external_source"), nullable=False),
        _uuid_pk(),
        *_timestamps(),
        _pk("episode_order"),
        # Deferrable so re-ranking a whole numbering after TMDB inserts an episode is a single UPDATE.
        sa.UniqueConstraint(
            "title_id",
            "order_type",
            "label",
            "sequence",
            name=op.f("uq_episode_order_title_id_order_type_label_sequence"),
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.UniqueConstraint(
            "episode_id", "order_type", "label", name=op.f("uq_episode_order_episode_id_order_type_label")
        ),
        sa.CheckConstraint("sequence >= 1", name=op.f("ck_episode_order_sequence_positive")),
        sa.CheckConstraint(
            "order_season_number IS NULL OR order_season_number >= 0",
            name=op.f("ck_episode_order_order_season_non_negative"),
        ),
        sa.CheckConstraint(
            "order_episode_number IS NULL OR order_episode_number >= 0",
            name=op.f("ck_episode_order_order_episode_non_negative"),
        ),
    )
    op.create_index(op.f("ix_episode_order_title_id"), "episode_order", ["title_id"])
    op.create_index(op.f("ix_episode_order_episode_id"), "episode_order", ["episode_id"])


def _external_id() -> None:
    op.create_table(
        "external_id",
        sa.Column("entity_kind", _enum("entity_kind"), nullable=False),
        sa.Column("source", _enum("external_source"), nullable=False),
        sa.Column("value", sa.String(120), nullable=False),
        # Three typed FKs rather than a polymorphic pair: a polymorphic id can neither cascade nor be trusted,
        # and this is the Phase 3 join surface where a dangling one becomes a video that will not play.
        _fk("external_id", "title_id", "title.id", "CASCADE", nullable=True),
        _fk("external_id", "season_id", "season.id", "CASCADE", nullable=True),
        _fk("external_id", "episode_id", "episode.id", "CASCADE", nullable=True),
        _uuid_pk(),
        *_timestamps(),
        _pk("external_id"),
        sa.UniqueConstraint("source", "entity_kind", "value", name=op.f("uq_external_id_source_entity_kind_value")),
        sa.CheckConstraint("num_nonnulls(title_id, season_id, episode_id) = 1", name=op.f("ck_external_id_one_entity")),
        sa.CheckConstraint(
            "(entity_kind = 'title' AND title_id IS NOT NULL) OR (entity_kind = 'season' AND season_id IS NOT NULL)"
            " OR (entity_kind = 'episode' AND episode_id IS NOT NULL)",
            name=op.f("ck_external_id_kind_matches_column"),
        ),
    )
    op.create_index(op.f("ix_external_id_title_id"), "external_id", ["title_id"])
    op.create_index(op.f("ix_external_id_season_id"), "external_id", ["season_id"])
    op.create_index(op.f("ix_external_id_episode_id"), "external_id", ["episode_id"])


def _artwork() -> None:
    op.create_table(
        "artwork",
        sa.Column("entity_kind", _enum("entity_kind"), nullable=False),
        sa.Column("kind", _enum("artwork_kind"), nullable=False),
        sa.Column("source", _enum("external_source"), nullable=False),
        sa.Column("remote_path", sa.String(500), nullable=False),
        # A path into app/heroes/, never the bytes: that directory already owns caching and attribution.
        sa.Column("local_path", sa.String(500)),
        sa.Column("width", sa.Integer),
        sa.Column("height", sa.Integer),
        sa.Column("aspect_ratio", sa.Numeric(6, 4)),
        sa.Column("language", sa.String(16)),
        sa.Column("vote_average", sa.Numeric(4, 2)),
        sa.Column("is_primary", sa.Boolean, server_default=sa.text("false"), nullable=False),
        _fk("artwork", "title_id", "title.id", "CASCADE", nullable=True),
        _fk("artwork", "season_id", "season.id", "CASCADE", nullable=True),
        _fk("artwork", "episode_id", "episode.id", "CASCADE", nullable=True),
        _uuid_pk(),
        *_timestamps(),
        _pk("artwork"),
        sa.UniqueConstraint("source", "remote_path", name=op.f("uq_artwork_source_remote_path")),
        sa.CheckConstraint("num_nonnulls(title_id, season_id, episode_id) = 1", name=op.f("ck_artwork_one_entity")),
        sa.CheckConstraint(
            "(entity_kind = 'title' AND title_id IS NOT NULL) OR (entity_kind = 'season' AND season_id IS NOT NULL)"
            " OR (entity_kind = 'episode' AND episode_id IS NOT NULL)",
            name=op.f("ck_artwork_kind_matches_column"),
        ),
        sa.CheckConstraint("width IS NULL OR width > 0", name=op.f("ck_artwork_width_positive")),
        sa.CheckConstraint("height IS NULL OR height > 0", name=op.f("ck_artwork_height_positive")),
    )
    # Three partial uniques rather than one composite: each is both the constraint and the lookup path for
    # "the primary poster of this title".
    for entity in ("title", "season", "episode"):
        op.create_index(
            op.f(f"ix_artwork_primary_{entity}"),
            "artwork",
            [f"{entity}_id", "kind"],
            unique=True,
            postgresql_where=sa.text(f"is_primary AND {entity}_id IS NOT NULL"),
        )


def _curated_entry() -> None:
    op.create_table(
        "curated_entry",
        _fk("curated_entry", "category_id", "category.id", "RESTRICT"),
        # Straight off the sheet. Postgres never invents, reorders or corrects it.
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("sheet_row", sa.Integer),
        _fk("curated_entry", "title_id", "title.id", "SET NULL", nullable=True),
        sa.Column("unit_kind", _enum("unit_kind"), server_default="unknown", nullable=False),
        sa.Column("order_type", sa.String(32)),
        sa.Column("order_label", sa.String(120), server_default="", nullable=False),
        sa.Column("span_start", sa.Integer),
        sa.Column("span_end", sa.Integer),
        sa.Column("season_number", sa.Integer),
        sa.Column("resolution_state", _enum("resolution_state"), server_default="unresolved", nullable=False),
        sa.Column("resolution_confidence", sa.Numeric(3, 2)),
        sa.Column("resolution_note", sa.Text, server_default="", nullable=False),
        # The verbatim row: nineteen workbooks with different headers would otherwise need nineteen schemas.
        sa.Column("raw_cells", postgresql.JSONB, nullable=False),
        sa.Column("raw_title", sa.Text, server_default="", nullable=False),
        sa.Column("raw_unit", sa.Text, server_default="", nullable=False),
        sa.Column("raw_release", sa.Text, server_default="", nullable=False),
        sa.Column("match_key", sa.String(255)),
        # What the sheet last said, and what this app last wrote into it. Both, or the reconciler cannot tell
        # its own echo from a human edit in Excel.
        sa.Column("observed_watch_cell", sa.String(32), server_default="", nullable=False),
        sa.Column("mirrored_watch_cell", sa.String(32), server_default="", nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True)),
        _uuid_pk(),
        *_timestamps(),
        _pk("curated_entry"),
        sa.UniqueConstraint(
            "category_id",
            "position",
            name=op.f("uq_curated_entry_category_id_position"),
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.CheckConstraint("position >= 1", name=op.f("ck_curated_entry_position_positive")),
        sa.CheckConstraint("sheet_row IS NULL OR sheet_row >= 2", name=op.f("ck_curated_entry_sheet_row_below_header")),
        sa.CheckConstraint("span_start IS NULL OR span_start >= 1", name=op.f("ck_curated_entry_span_start_positive")),
        sa.CheckConstraint("span_end IS NULL OR span_end >= 1", name=op.f("ck_curated_entry_span_end_positive")),
        sa.CheckConstraint(
            "span_start IS NULL OR span_end IS NULL OR span_end >= span_start",
            name=op.f("ck_curated_entry_span_ordered"),
        ),
        sa.CheckConstraint(
            "season_number IS NULL OR season_number >= 0", name=op.f("ck_curated_entry_season_number_non_negative")
        ),
        sa.CheckConstraint(
            "resolution_confidence IS NULL OR (resolution_confidence >= 0 AND resolution_confidence <= 1)",
            name=op.f("ck_curated_entry_confidence_unit_interval"),
        ),
    )
    op.create_index(op.f("ix_curated_entry_category_id"), "curated_entry", ["category_id"])
    # The review queue's own index: unresolved and auto are first-class states, not an error condition.
    op.create_index(
        op.f("ix_curated_entry_needs_review"),
        "curated_entry",
        ["category_id", "position"],
        postgresql_where=sa.text("removed_at IS NULL AND resolution_state IN ('unresolved', 'auto')"),
    )
    op.create_index(op.f("ix_curated_entry_resolution_state"), "curated_entry", ["resolution_state"])
    op.create_index(op.f("ix_curated_entry_match_key"), "curated_entry", ["match_key"])
    op.create_index(op.f("ix_curated_entry_title_id"), "curated_entry", ["title_id"])


def _curated_entry_item() -> None:
    # No timestamps: this table is rebuilt delete-then-insert inside the ingest transaction, so a
    # created_at would record when the cache was last rebuilt and nothing a reader could use.
    op.create_table(
        "curated_entry_item",
        _fk("curated_entry_item", "category_id", "category.id", "RESTRICT"),
        _fk("curated_entry_item", "curated_entry_id", "curated_entry.id", "CASCADE"),
        _fk("curated_entry_item", "episode_id", "episode.id", "CASCADE", nullable=True),
        # Exactly one row per movie entry, so Next and Autoplay follow the curated order through a film.
        _fk("curated_entry_item", "movie_title_id", "title.id", "CASCADE", nullable=True),
        sa.Column("position_in_entry", sa.Integer, nullable=False),
        sa.Column("absolute_position", sa.Integer, nullable=False),
        _uuid_pk(),
        _pk("curated_entry_item"),
        sa.UniqueConstraint(
            "category_id",
            "absolute_position",
            name=op.f("uq_curated_entry_item_category_id_absolute_position"),
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.UniqueConstraint(
            "curated_entry_id",
            "position_in_entry",
            name=op.f("uq_curated_entry_item_curated_entry_id_position_in_entry"),
        ),
        sa.CheckConstraint(
            "num_nonnulls(episode_id, movie_title_id) = 1", name=op.f("ck_curated_entry_item_one_playable_unit")
        ),
        sa.CheckConstraint("position_in_entry >= 1", name=op.f("ck_curated_entry_item_position_in_entry_positive")),
        sa.CheckConstraint("absolute_position >= 1", name=op.f("ck_curated_entry_item_absolute_position_positive")),
    )
    op.create_index(op.f("ix_curated_entry_item_episode_id"), "curated_entry_item", ["episode_id"])
    op.create_index(op.f("ix_curated_entry_item_curated_entry_id"), "curated_entry_item", ["curated_entry_id"])
    op.create_index(op.f("ix_curated_entry_item_category_id"), "curated_entry_item", ["category_id"])


def _watch_event() -> None:
    # No timestamps mixin: an append-only table has no updated_at, and giving it one would be a lie the
    # next reader has to disprove.
    op.create_table(
        "watch_event",
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("subject_kind", _enum("watch_subject_kind"), nullable=False),
        sa.Column("kind", _enum("watch_event_kind"), nullable=False),
        sa.Column("source", _enum("watch_event_source"), nullable=False),
        # `movie:603`, `tv:1399:s2:e5` - the durable pointer a full metadata rebuild re-links against.
        sa.Column("tmdb_key", sa.String(64)),
        _fk("watch_event", "episode_id", "episode.id", "SET NULL", nullable=True),
        _fk("watch_event", "title_id", "title.id", "SET NULL", nullable=True),
        # RESTRICT, so the soft delete of a curated entry is a database rule and not a convention.
        _fk("watch_event", "curated_entry_id", "curated_entry.id", "RESTRICT", nullable=True),
        _fk("watch_event", "category_id", "category.id", "RESTRICT", nullable=True),
        sa.Column("position_seconds", sa.Integer),
        sa.Column("runtime_seconds", sa.Integer),
        sa.Column("device", sa.String(120)),
        sa.Column("note", sa.String(240)),
        _uuid_pk(),
        _pk("watch_event"),
        sa.CheckConstraint(
            "num_nonnulls(episode_id, title_id, curated_entry_id) = 1", name=op.f("ck_watch_event_one_subject")
        ),
        sa.CheckConstraint(
            "(subject_kind = 'episode' AND episode_id IS NOT NULL)"
            " OR (subject_kind = 'title' AND title_id IS NOT NULL)"
            " OR (subject_kind = 'curated_entry' AND curated_entry_id IS NOT NULL)",
            name=op.f("ck_watch_event_kind_matches_column"),
        ),
        sa.CheckConstraint(
            "position_seconds IS NULL OR position_seconds >= 0",
            name=op.f("ck_watch_event_position_seconds_non_negative"),
        ),
        sa.CheckConstraint(
            "runtime_seconds IS NULL OR runtime_seconds > 0", name=op.f("ck_watch_event_runtime_seconds_positive")
        ),
        sa.CheckConstraint(
            "kind <> 'progressed' OR position_seconds IS NOT NULL", name=op.f("ck_watch_event_progressed_has_position")
        ),
    )
    op.create_index(op.f("ix_watch_event_tmdb_key"), "watch_event", ["tmdb_key"])
    # Ordered the way the two DISTINCT ON views read them.
    for subject, slot in (("title", "title"), ("curated_entry", "entry"), ("episode", "episode")):
        op.create_index(
            op.f(f"ix_watch_event_{slot}_latest"),
            "watch_event",
            [f"{subject}_id", "occurred_at", "recorded_at", "id"],
            postgresql_where=sa.text(f"{subject}_id IS NOT NULL"),
        )


def _sync_state() -> None:
    op.create_table(
        "sync_state",
        sa.Column("source", _enum("external_source"), nullable=False),
        sa.Column("resource_type", _enum("sync_resource_type"), nullable=False),
        sa.Column("resource_key", sa.String(200), nullable=False),
        sa.Column("etag", sa.String(200)),
        sa.Column("last_modified", sa.String(64)),
        # TMDB does not send an ETag on every endpoint; an unchanged digest is what skips the write path.
        sa.Column("payload_digest", sa.String(64)),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("consecutive_failures", sa.Integer, server_default=sa.text("0"), nullable=False),
        sa.Column("last_error", sa.Text),
        _uuid_pk(),
        *_timestamps(),
        _pk("sync_state"),
        sa.UniqueConstraint(
            "source", "resource_type", "resource_key", name=op.f("uq_sync_state_source_resource_type_resource_key")
        ),
        sa.CheckConstraint("consecutive_failures >= 0", name=op.f("ck_sync_state_failures_non_negative")),
    )
    op.create_index(
        op.f("ix_sync_state_due"),
        "sync_state",
        ["next_attempt_at"],
        postgresql_where=sa.text("next_attempt_at IS NOT NULL"),
    )


def upgrade() -> None:
    """Upgrade schema."""
    # pg_trgm first: title's trigram index cannot be built without the operator class it installs.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    for name, labels in ENUMS.items():
        op.execute(_create_type(name, labels))

    _category()
    _title()
    _season()
    _episode()
    _episode_order()
    _external_id()
    _artwork()
    _curated_entry()
    _curated_entry_item()
    _watch_event()
    _sync_state()

    # A service-layer convention is not enough: an Alembic data migration, a psql session or a
    # session.merge() on a detached instance would each rewrite history silently.
    op.execute(WATCH_EVENT_FUNCTION)
    op.execute(WATCH_EVENT_TRIGGER)
    # The entry view reads the episode view, so the episode view is created first.
    op.execute(EPISODE_WATCH_STATE)
    op.execute(CURATED_ENTRY_WATCH_STATE)


def downgrade() -> None:
    """Downgrade schema."""
    # Hand-ordered, because autogenerate knows about none of it: the views before the tables they read, the
    # trigger and its function before watch_event, the tables in reverse dependency order, then the types.
    op.execute("DROP VIEW IF EXISTS curated_entry_watch_state")
    op.execute("DROP VIEW IF EXISTS episode_watch_state")
    op.execute("DROP TRIGGER IF EXISTS watch_event_no_mutation ON watch_event")
    op.execute("DROP FUNCTION IF EXISTS watch_event_reject_mutation()")
    for table in reversed(TABLES_IN_DEPENDENCY_ORDER):
        op.drop_table(table)
    for name in reversed(ENUMS):
        op.execute(f"DROP TYPE {name}")
    # pg_trgm is deliberately left installed: another schema in the same database may be using it, and
    # creating an extension is not the same as owning it.
