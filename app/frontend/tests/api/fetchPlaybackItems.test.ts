import { expect, it } from "vitest";

import { fetchPlaybackItems } from "../../src/api/fetchPlaybackItems";
import { aFakeServer } from "../support/aFakeServer";
import { aPlaybackItemRead } from "../support/aPlaybackItemRead";

it("keeps missing, ambiguous and shared-file slots in the returned order", async () => {
  const server = aFakeServer();
  const slots = [
    aPlaybackItemRead({ id: "missing", availability: "not_in_library", jellyfin_item_id: null }),
    aPlaybackItemRead({ id: "ambiguous", availability: "ambiguous", jellyfin_item_id: null }),
    aPlaybackItemRead({ id: "range-one", covers_range: true }),
    aPlaybackItemRead({ id: "range-two", covers_range: true }),
  ];
  server.answers("GET /api/playback/entries/entry%2Fid/items", slots);
  expect(await fetchPlaybackItems("entry/id")).toEqual(slots);
  expect(server.requests[0]?.query).toBe("?limit=500&offset=0");
});
