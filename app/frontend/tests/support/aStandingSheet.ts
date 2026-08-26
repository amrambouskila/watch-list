import type { StandingRows } from "../../src/types/StandingRows";

/** The sheet a pending edit targets, read and keyed by the row numbers a proposal would name. */
export function aReadSheet(
  identifyingKey: string | null,
  cellsByRow: Record<number, Record<string, string>>,
): StandingRows {
  return { status: "ready", identifyingKey, cellsByRow };
}

/** The sheet while the read is still in flight. */
export function aSheetBeingRead(): StandingRows {
  return { status: "loading", identifyingKey: null, cellsByRow: {} };
}

/** The sheet after the read failed, so nothing about it is known. */
export function anUnreadableSheet(): StandingRows {
  return { status: "failed", identifyingKey: null, cellsByRow: {} };
}
