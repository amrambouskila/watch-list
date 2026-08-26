import { describe, expect, it } from "vitest";

import type { RowChange } from "../../src/types/RowChange";
import { anchorOf } from "../../src/utils/anchorOf";
import { aReadSheet, aSheetBeingRead } from "../support/aStandingSheet";

const SHEET = aReadSheet("title", { 3: { title: "Third" }, 5: { title: "Fifth" } });

function change(draft: Partial<RowChange> & Pick<RowChange, "kind">): RowChange {
  return { cells: {}, reason: "", ...draft };
}

describe("anchorOf", () => {
  it("seats an addition at the end when it names no row to follow", () => {
    expect(anchorOf(change({ kind: "add" }), SHEET)).toBe("at the end");
  });

  it("seats an addition after the row it names", () => {
    expect(anchorOf(change({ kind: "add", after_row: 5 }), SHEET)).toBe("after 5");
  });

  it.each(["revise", "remove"] as const)("gives a %s the row it targets", (kind) => {
    expect(anchorOf(change({ kind, row: 3 }), SHEET)).toBe("3");
  });

  it("marks a change that names no row at all rather than inventing one", () => {
    expect(anchorOf(change({ kind: "revise" }), SHEET)).toBe("—");
  });

  it("names the destination of a move, not just its number", () => {
    expect(anchorOf(change({ kind: "move", row: 3, after_row: 5 }), SHEET)).toBe("3 → after 5 · Fifth");
  });

  it("reads a move behind the header row as a move to the top", () => {
    expect(anchorOf(change({ kind: "move", row: 3, after_row: 1 }), SHEET)).toBe("3 → to the top");
  });

  it("says plainly when the destination cannot be named because the sheet has not been read", () => {
    expect(anchorOf(change({ kind: "move", row: 3, after_row: 5 }), aSheetBeingRead())).toBe(
      "3 → after 5 · reading the sheet…",
    );
  });

  it("says plainly when the destination row is no longer in the sheet", () => {
    expect(anchorOf(change({ kind: "move", row: 3, after_row: 99 }), SHEET)).toBe("3 → after 99 · no such row now");
  });

  it("falls back to the bare number when the sheet has no column to name the destination with", () => {
    const unnamed = aReadSheet(null, { 5: { note: "kept" } });

    expect(anchorOf(change({ kind: "move", row: 3, after_row: 5 }), unnamed)).toBe("3 → after 5");
  });

  it("marks a move whose destination is missing rather than showing it as landing nowhere in particular", () => {
    expect(anchorOf(change({ kind: "move", row: 3 }), SHEET)).toBe("3 → —");
  });
});
