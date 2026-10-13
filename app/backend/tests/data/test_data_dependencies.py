from __future__ import annotations

from importlib import import_module
from importlib.metadata import version

import pytest
from packaging.version import Version

FLOORS = {"sqlalchemy": "2.0.36", "asyncpg": "0.30.0", "alembic": "1.14.0"}


@pytest.mark.parametrize("distribution", sorted(FLOORS))
def test_the_data_layer_dependency_meets_its_floor(distribution: str) -> None:
    assert Version(version(distribution)) >= Version(FLOORS[distribution])


def test_the_async_extension_is_importable() -> None:
    module = import_module("sqlalchemy.ext.asyncio")
    assert hasattr(module, "create_async_engine")
