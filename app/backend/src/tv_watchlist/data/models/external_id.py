"""One provider id for one entity. Three typed FKs, not a polymorphic pair, so the id can cascade and be trusted."""

from __future__ import annotations

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from tv_watchlist.data.base import Base, TimestampMixin, UuidPk
from tv_watchlist.data.enums import EntityKind, ExternalSource, pg_enum


class ExternalId(UuidPk, TimestampMixin, Base):
    """The Phase 3 Jellyfin join surface: a dangling id here surfaces as a video that will not play."""

    __tablename__ = "external_id"
    __table_args__ = (
        UniqueConstraint("source", "entity_kind", "value"),
        CheckConstraint("num_nonnulls(title_id, season_id, episode_id) = 1", name="one_entity"),
        CheckConstraint(
            "(entity_kind = 'title' AND title_id IS NOT NULL) OR (entity_kind = 'season' AND season_id IS NOT NULL)"
            " OR (entity_kind = 'episode' AND episode_id IS NOT NULL)",
            name="kind_matches_column",
        ),
    )

    entity_kind: Mapped[EntityKind] = mapped_column(pg_enum(EntityKind, "entity_kind"))
    source: Mapped[ExternalSource] = mapped_column(pg_enum(ExternalSource, "external_source"))
    value: Mapped[str] = mapped_column(String(120))
    title_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("title.id", ondelete="CASCADE"), index=True)
    season_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("season.id", ondelete="CASCADE"), index=True)
    episode_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("episode.id", ondelete="CASCADE"), index=True)
