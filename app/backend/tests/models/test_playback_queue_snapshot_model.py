from __future__ import annotations

import pytest
from pydantic import ValidationError

from tv_watchlist.models.playback_queue_snapshot import PlaybackQueueSnapshot


def test_queue_snapshot_is_frozen_and_has_exact_fields() -> None:
    digest = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    value = PlaybackQueueSnapshot(fingerprint=digest, occurrences=())
    assert list(type(value).model_fields) == ["fingerprint", "occurrences"]
    assert value.model_dump(mode="json") == {"fingerprint": digest, "occurrences": []}
    with pytest.raises(ValidationError, match="frozen"):
        value.fingerprint = "0" * 64


@pytest.mark.parametrize("digest", ["", "a" * 63, "A" * 64, "g" * 64])
def test_fingerprint_requires_lowercase_sha256(digest: str) -> None:
    with pytest.raises(ValidationError):
        PlaybackQueueSnapshot(fingerprint=digest, occurrences=())


def test_queue_snapshot_refuses_unapproved_fields() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        PlaybackQueueSnapshot.model_validate({"fingerprint": "0" * 64, "occurrences": [], "skip": True})
