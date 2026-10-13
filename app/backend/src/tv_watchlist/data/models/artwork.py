"""Image metadata. Bytes live under app/heroes/ (with ATTRIBUTION.md), never in Postgres."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from tv_watchlist.data.base import Base, TimestampMixin, UuidPk
from tv_watchlist.data.enums import ArtworkKind, EntityKind, ExternalSource, pg_enum


class Artwork(UuidPk, TimestampMixin, Base):
    """Three partial unique indexes: each is both the constraint and the lookup path for 'the primary poster'."""

    __tablename__ = "artwork"
    __table_args__ = (
        UniqueConstraint("source", "remote_path"),
        CheckConstraint("num_nonnulls(title_id, season_id, episode_id) = 1", name="one_entity"),
        CheckConstraint(
            "(entity_kind = 'title' AND title_id IS NOT NULL) OR (entity_kind = 'season' AND season_id IS NOT NULL)"
            " OR (entity_kind = 'episode' AND episode_id IS NOT NULL)",
            name="kind_matches_column",
        ),
        CheckConstraint("width IS NULL OR width > 0", name="width_positive"),
        CheckConstraint("height IS NULL OR height > 0", name="height_positive"),
        Index(
            "ix_artwork_primary_title",
            "title_id",
            "kind",
            unique=True,
            postgresql_where=text("is_primary AND title_id IS NOT NULL"),
        ),
        Index(
            "ix_artwork_primary_season",
            "season_id",
            "kind",
            unique=True,
            postgresql_where=text("is_primary AND season_id IS NOT NULL"),
        ),
        Index(
            "ix_artwork_primary_episode",
            "episode_id",
            "kind",
            unique=True,
            postgresql_where=text("is_primary AND episode_id IS NOT NULL"),
        ),
    )

    entity_kind: Mapped[EntityKind] = mapped_column(pg_enum(EntityKind, "entity_kind"))
    kind: Mapped[ArtworkKind] = mapped_column(pg_enum(ArtworkKind, "artwork_kind"))
    source: Mapped[ExternalSource] = mapped_column(pg_enum(ExternalSource, "external_source"))
    remote_path: Mapped[str] = mapped_column(String(500))
    local_path: Mapped[str | None] = mapped_column(String(500))
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    aspect_ratio: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    language: Mapped[str | None] = mapped_column(String(16))
    vote_average: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    title_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("title.id", ondelete="CASCADE"))
    season_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("season.id", ondelete="CASCADE"))
    episode_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("episode.id", ondelete="CASCADE"))
