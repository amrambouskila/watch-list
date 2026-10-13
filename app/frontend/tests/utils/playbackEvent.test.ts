import { expect, it } from "vitest";

import { playbackEvent } from "../../src/utils/playbackEvent";
import { aPlaybackItemRead } from "../support/aPlaybackItemRead";

it("rounds seconds once and identifies an episode without guessing its file siblings", () => {
  expect(playbackEvent(aPlaybackItemRead(), "progressed", 60.6, 120.4, "now")).toEqual({
    subject_kind: "episode", subject_id: aPlaybackItemRead().episode_id, kind: "progressed",
    occurred_at: "now", position_seconds: 61, runtime_seconds: 120,
  });
});

it("uses title for a movie and clips a coherent ended position to the file runtime", () => {
  expect(playbackEvent(aPlaybackItemRead({ episode_id: null, movie_title_id: "movie" }),
    "completed", 121, 120, "now")).toMatchObject({ subject_kind: "title", subject_id: "movie",
    kind: "completed", position_seconds: 120, runtime_seconds: 120 });
});

it.each([NaN, Infinity, -1])("refuses invalid media positions: %s", (position) => {
  expect(playbackEvent(aPlaybackItemRead(), "progressed", position, 120, "now")).toBeNull();
});

it.each([NaN, Infinity, 0, -1, 0.1])("refuses ended without a positive integer runtime: %s", (runtime) => {
  expect(playbackEvent(aPlaybackItemRead(), "completed", 120, runtime, "now")).toBeNull();
});

it("never threshold-completes and allows unknown duration for progress", () => {
  expect(playbackEvent(aPlaybackItemRead(), "progressed", 119, 120, "now")?.kind).toBe("progressed");
  expect(playbackEvent(aPlaybackItemRead(), "progressed", 121, 120, "now"))
    .toMatchObject({ kind: "progressed", position_seconds: 120 });
  expect(playbackEvent(aPlaybackItemRead(), "progressed", 60, NaN, "now")?.runtime_seconds).toBeNull();
  expect(playbackEvent(aPlaybackItemRead(), "completed", 119, 120, "now")).toBeNull();
  expect(playbackEvent(aPlaybackItemRead({ episode_id: null, movie_title_id: null }),
    "progressed", 60, 120, "now")).toBeNull();
});
