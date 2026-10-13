from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from tv_watchlist.models.import_file_identity import ImportFileIdentity


def test_stat_identity_round_trips_as_frozen_json(tmp_path: Path) -> None:
    path = tmp_path / "file"
    path.write_bytes(b"abc")
    identity = ImportFileIdentity.from_stat(path.stat())
    assert identity.size_bytes == 3
    assert ImportFileIdentity.model_validate(identity.model_dump()) == identity
    assert identity.same_file(ImportFileIdentity.from_stat(path.stat()))
    with pytest.raises(ValidationError):
        identity.size_bytes = 4


@pytest.mark.parametrize("field", ["device", "inode", "size_bytes"])
def test_negative_identity_fields_are_refused(field: str) -> None:
    values = {"device": 1, "inode": 1, "size_bytes": 1, "mtime_ns": 1}
    values[field] = -1
    with pytest.raises(ValidationError):
        ImportFileIdentity.model_validate(values)
