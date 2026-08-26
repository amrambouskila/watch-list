import { describe, expect, it } from "vitest";

import { identifyRow } from "../../src/utils/identifyRow";
import { aReadSheet, aSheetBeingRead, anUnreadableSheet } from "../support/aStandingSheet";

const SHEET = aReadSheet("title", { 2: { title: "The Standing Row", note: "kept" }, 3: { title: "" } });

describe("identifyRow", () => {
  it("names the row by the cell a reader would recognise it from", () => {
    expect(identifyRow(SHEET, 2)).toBe("The Standing Row");
  });

  it("says the sheet is still being read rather than showing an empty column", () => {
    expect(identifyRow(aSheetBeingRead(), 2)).toBe("reading the sheet…");
  });

  it("says the sheet could not be read rather than showing an empty column", () => {
    expect(identifyRow(anUnreadableSheet(), 2)).toBe("could not read the sheet");
  });

  it("says the row is gone when the sheet no longer holds it", () => {
    expect(identifyRow(SHEET, 99)).toBe("no such row now");
  });

  it("is silent when the sheet has no column that identifies a row", () => {
    expect(identifyRow(aReadSheet(null, { 2: { note: "kept" } }), 2)).toBe("");
  });

  it("is silent when the identifying cell of that row is itself empty", () => {
    expect(identifyRow(SHEET, 3)).toBe("");
  });
});
