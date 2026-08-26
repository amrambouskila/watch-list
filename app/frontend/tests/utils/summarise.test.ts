import { describe, expect, it } from "vitest";

import type { WatchCounts } from "../../src/types/WatchCounts";
import { summarise } from "../../src/utils/summarise";

function counts(draft: Partial<WatchCounts>): WatchCounts {
  return { total: 0, watched: 0, in_progress: 0, skipped: 0, unwatched: 0, trackable: 0, ...draft };
}

describe("summarise", () => {
  it("counts a single entry in the singular", () => {
    expect(summarise(counts({ total: 1, trackable: 1 }))).toBe("1 entry · 0 watched");
  });

  it("counts several entries in the plural", () => {
    expect(summarise(counts({ total: 12, watched: 5, trackable: 12 }))).toBe("12 entries · 5 watched");
  });

  it("counts an empty category in the plural too", () => {
    expect(summarise(counts({}))).toBe("0 entries · 0 watched");
  });

  it("mentions what is being watched only when something is", () => {
    expect(summarise(counts({ total: 4, watched: 1, in_progress: 2, trackable: 4 }))).toBe(
      "4 entries · 1 watched · 2 watching",
    );
  });

  it("mentions what was skipped only when something was", () => {
    expect(summarise(counts({ total: 4, watched: 1, skipped: 3, trackable: 1 }))).toBe(
      "4 entries · 1 watched · 3 skipped",
    );
  });

  it("keeps watching before skipped when both apply", () => {
    expect(summarise(counts({ total: 6, watched: 1, in_progress: 2, skipped: 3, trackable: 3 }))).toBe(
      "6 entries · 1 watched · 2 watching · 3 skipped",
    );
  });
});
