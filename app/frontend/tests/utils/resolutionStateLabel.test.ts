import { describe, expect, it } from "vitest";

import type { ResolutionState } from "../../src/types/CuratedEntryRead";
import { resolutionStateLabel } from "../../src/utils/resolutionStateLabel";

describe("resolutionStateLabel", () => {
  it.each<[ResolutionState, string]>([
    ["unresolved", "Unresolved"],
    ["auto", "Auto"],
    ["confirmed", "Confirmed"],
    ["rejected", "Rejected"],
  ])("reads %s as %s", (state, label) => {
    expect(resolutionStateLabel(state)).toBe(label);
  });
});
