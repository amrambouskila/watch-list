from __future__ import annotations

import uuid

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, MetaData, String, Table, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from tv_watchlist.data.base import NAMING_CONVENTION, Base, TimestampMixin, UuidPk


class _ProbeBase(DeclarativeBase):
    """A throwaway registry, so this probe never lands on Base.metadata (T06 asserts its exact table set)."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class _ProbeParent(UuidPk, _ProbeBase):
    """Exists only to give the probe a foreign key to point at."""

    __tablename__ = "probe_parent_for_base_test"


class _Probe(UuidPk, TimestampMixin, _ProbeBase):
    """One table carrying all five constraint kinds, so every naming template is exercised."""

    __tablename__ = "probe_for_base_test"
    __table_args__ = (CheckConstraint("count >= 0", name="count_is_not_negative"), Index(None, "count"))

    label: Mapped[str] = mapped_column(String(10), unique=True)
    count: Mapped[int] = mapped_column(Integer)
    parent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("probe_parent_for_base_test.id"))


def _probe_table() -> Table:
    return _ProbeBase.metadata.tables["probe_for_base_test"]


def test_the_metadata_carries_the_naming_convention() -> None:
    assert isinstance(Base.metadata, MetaData)
    assert Base.metadata.naming_convention == NAMING_CONVENTION


def test_every_naming_template_produces_the_name_it_promises() -> None:
    table = _probe_table()
    assert {constraint.name for constraint in table.constraints} == {
        "pk_probe_for_base_test",
        "uq_probe_for_base_test_label",
        "ck_probe_for_base_test_count_is_not_negative",
        "fk_probe_for_base_test_parent_id_probe_parent_for_base_test",
    }
    assert {index.name for index in table.indexes} == {"ix_probe_for_base_test_count"}


def test_the_primary_key_is_a_uuid_minted_on_both_sides() -> None:
    column = _probe_table().c.id
    assert isinstance(column.type, Uuid)
    assert column.primary_key
    minted = column.default
    assert minted is not None and minted.is_callable
    # SQLAlchemy wraps a zero-argument default in a context-taking callable; `__wrapped__` is the original.
    assert getattr(minted.arg, "__wrapped__", minted.arg) is uuid.uuid4
    assert column.server_default is not None and "gen_random_uuid()" in str(column.server_default.arg)


def test_timestamps_are_timezone_aware_with_server_defaults() -> None:
    table = _probe_table()
    for name in ("created_at", "updated_at"):
        column = table.c[name]
        assert isinstance(column.type, DateTime) and column.type.timezone
        assert column.server_default is not None
    assert table.c.updated_at.onupdate is not None
