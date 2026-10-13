"""What one mirror pass did to one workbook."""

from __future__ import annotations

from typing import Final, Literal

MirrorOutcome = Literal["unchanged", "written", "deferred"]

# The projection already matched the cell, or the sheet has no status column to project onto. Nothing
# was opened, so nothing was snapshotted and no stamp moved.
UNCHANGED: Final[MirrorOutcome] = "unchanged"
# The cells went in through `Catalog._write`, and `mirrored_watch_cell`, `workbook_mtime` and
# `last_mirrored_at` moved with them, in the same transaction.
WRITTEN: Final[MirrorOutcome] = "written"
# The mirror declined: Excel holds the file, the swap was refused, or the sheet moved under the plan.
# Neither store changed, so the identical diff replays on the next pass (master plan section 6.6).
DEFERRED: Final[MirrorOutcome] = "deferred"
