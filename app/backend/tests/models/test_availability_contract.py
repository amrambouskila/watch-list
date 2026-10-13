from __future__ import annotations

from ts_types import ts_source
from tv_watchlist.data.enums import Availability


def test_the_availability_members_match_the_typescript_union() -> None:
    spelled = " | ".join(f'"{member.value}"' for member in Availability)
    assert f"export type Availability = {spelled};" in ts_source("Availability").splitlines()
