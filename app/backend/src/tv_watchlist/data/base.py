"""Declarative base, the naming convention, and the two column mixins every table shares."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Final

from sqlalchemy import DateTime, MetaData, Uuid, func, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Without a convention Alembic autogenerate emits unnamed constraints it can never drop again.
# The `ck` template interpolates `constraint_name`, so every CheckConstraint must be given an explicit
# `name=` (the short form, without the `ck_<table>_` prefix); an unnamed one raises at import time.
NAMING_CONVENTION: Final[dict[str, str]] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Every model under `data/models/` extends this, so `Base.metadata` is the whole schema."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UuidPk:
    """UUID primary key minted client-side, so the reconciler knows a row's id before flush."""

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )


class TimestampMixin:
    """`created_at` / `updated_at` as timestamptz. Append-only tables deliberately do not use it."""

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
