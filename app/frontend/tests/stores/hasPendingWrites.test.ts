import { expect, it } from "vitest";

import { writeRow } from "../../src/stores/categorySlice";
import { hasPendingWrites } from "../../src/stores/hasPendingWrites";
import { savePlaybackSnapshot } from "../../src/stores/playbackSavesSlice";
import { aPlaybackSnapshot } from "../support/aPlaybackSnapshot";
import { aTestStore } from "../support/aTestStore";

it("guards focus refresh for queued player writes as well as optimistic row edits", () => {
  const store = aTestStore();
  const snapshot = aPlaybackSnapshot();
  expect(hasPendingWrites(store.getState())).toBe(false);
  store.dispatch(savePlaybackSnapshot.pending("saving", snapshot));
  expect(hasPendingWrites(store.getState())).toBe(true);
  store.dispatch(savePlaybackSnapshot.rejected(new Error("Locked"), "saving", snapshot));
  expect(hasPendingWrites(store.getState())).toBe(false);
  store.dispatch(writeRow.pending("row", { categoryId: "category", row: 2, cells: {}, previous: {} }));
  expect(hasPendingWrites(store.getState())).toBe(true);
});
