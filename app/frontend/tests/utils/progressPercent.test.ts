import { describe, expect, it } from "vitest";

import { progressPercent } from "../../src/utils/progressPercent";
import type { WatchCounts } from "../../src/types/WatchCounts";

function counts(draft: Partial<WatchCounts>): WatchCounts {
  return { total: 0, watched: 0, in_progress: 0, skipped: 0, unwatched: 0, trackable: 0, ...draft };
}

describe("progressPercent", () => {
  it("is the share of the trackable entries that are finished", () => {
    expect(progressPercent(counts({ total: 10, watched: 3, trackable: 10 }))).toBe(30);
  });

  it("ignores skipped entries, which are not part of what is left to watch", () => {
    expect(progressPercent(counts({ total: 10, watched: 4, skipped: 2, trackable: 8 }))).toBe(50);
  });

  it("is 100 only when every trackable entry is watched", () => {
    expect(progressPercent(counts({ total: 5, watched: 5, trackable: 5 }))).toBe(100);
    expect(progressPercent(counts({ total: 5, watched: 4, trackable: 5 }))).toBe(80);
  });

  it("does not divide by zero on a category with nothing to track", () => {
    expect(progressPercent(counts({ total: 3, skipped: 3, trackable: 0 }))).toBe(0);
  });

  it("rounds rather than truncating, so one of three reads as 33", () => {
    expect(progressPercent(counts({ total: 3, watched: 1, trackable: 3 }))).toBe(33);
    expect(progressPercent(counts({ total: 3, watched: 2, trackable: 3 }))).toBe(67);
  });
});
