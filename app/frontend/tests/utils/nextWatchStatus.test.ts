import { describe, expect, it } from "vitest";

import { IN_PROGRESS, SKIPPED, UNWATCHED, WATCHED, WATCH_CYCLE } from "../../src/types/WatchStatus";
import { nextWatchStatus } from "../../src/utils/nextWatchStatus";

const SHEET_CHOICES = ["", "Seen", "Half", "Never"];

describe("nextWatchStatus", () => {
  it("advances through the sheet's own dropdown order rather than the app's", () => {
    expect(nextWatchStatus("", SHEET_CHOICES)).toBe("Seen");
    expect(nextWatchStatus("Seen", SHEET_CHOICES)).toBe("Half");
    expect(nextWatchStatus("Half", SHEET_CHOICES)).toBe("Never");
  });

  it("wraps at the end of the sheet's choices", () => {
    expect(nextWatchStatus("Never", SHEET_CHOICES)).toBe("");
  });

  it("falls back to the app's cycle when the sheet offers no choices", () => {
    expect(nextWatchStatus(UNWATCHED, [])).toBe(WATCHED);
    expect(nextWatchStatus(WATCHED, [])).toBe(IN_PROGRESS);
    expect(nextWatchStatus(IN_PROGRESS, [])).toBe(SKIPPED);
    expect(nextWatchStatus(SKIPPED, [])).toBe(UNWATCHED);
  });

  it("starts at the first choice when the cell holds something the dropdown does not offer", () => {
    expect(nextWatchStatus("Something the owner typed", SHEET_CHOICES)).toBe("");
  });

  it("covers every value the app's own cycle names", () => {
    const visited = WATCH_CYCLE.map((status) => nextWatchStatus(status, []));

    expect(new Set(visited)).toEqual(new Set(WATCH_CYCLE));
  });
});
