"""The frontend's type mirrors, read as text so a backend test can hold them to the Python contract.

A contract that crosses the wire is written twice - once as a Pydantic model, once as a TypeScript
interface - and the only thing that keeps the two spellings honest is a test that reads both
(CLAUDE.md section 21, item 12). Reading the `.ts` file rather than compiling it is deliberate: the
field names and the enum labels are the contract, and both are plain text.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

TYPES_DIR: Final[Path] = Path(__file__).resolve().parents[2] / "frontend" / "src" / "types"
# Two leading spaces is the interface body's indent in every file in that directory; a nested object
# literal would indent further, and these contracts have none. The optional marker is matched so a
# request body's `field?: T | null` reports the same name a response's `field: T | null` does.
_TS_FIELD: Final[re.Pattern[str]] = re.compile(r"^ {2}([a-z_][A-Za-z0-9_]*)\??:", re.MULTILINE)


# What an optional key looks like in an interface. A response has none - every field is serialised, so
# a nullable one is `T | null` - while a request body's defaulted fields are exactly the ones that do.
TS_OPTIONAL_KEY: Final[str] = "?:"


def ts_source(name: str) -> str:
    return (TYPES_DIR / f"{name}.ts").read_text(encoding="utf-8")


def ts_fields(name: str) -> list[str]:
    """The field names an interface file declares, in declaration order."""
    return _TS_FIELD.findall(ts_source(name))
