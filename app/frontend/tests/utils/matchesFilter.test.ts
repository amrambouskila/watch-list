import { describe, expect, it } from "vitest";

import { WATCH_FILTERS } from "../../src/types/WatchFilter";
import { IN_PROGRESS, SKIPPED, UNWATCHED, WATCHED } from "../../src/types/WatchStatus";
import { matchesFilter } from "../../src/utils/matchesFilter";

describe("matchesFilter", () => {
  it("keeps every row under the all filter, including values the sheet invented", () => {
    for (const status of [UNWATCHED, WATCHED, IN_PROGRESS, SKIPPED, "Rewatching"]) {
      expect(matchesFilter(status, "all")).toBe(true);
    }
  });

  it.each([
    ["unwatched", UNWATCHED],
    ["watched", WATCHED],
    ["in-progress", IN_PROGRESS],
    ["skipped", SKIPPED],
  ] as const)("keeps only the %s rows", (filter, status) => {
    expect(matchesFilter(status, filter)).toBe(true);
    for (const other of [UNWATCHED, WATCHED, IN_PROGRESS, SKIPPED].filter((value) => value !== status)) {
      expect(matchesFilter(other, filter)).toBe(false);
    }
  });

  it("hides a value the sheet holds that no filter names, rather than showing it under all of them", () => {
    for (const filter of WATCH_FILTERS.filter((candidate) => candidate !== "all")) {
      expect(matchesFilter("Rewatching", filter)).toBe(false);
    }
  });
});
