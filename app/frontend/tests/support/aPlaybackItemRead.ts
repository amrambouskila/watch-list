import type { PlaybackItemRead } from "../../src/types/PlaybackItemRead";

export function aPlaybackItemRead(overrides: Partial<PlaybackItemRead> = {}): PlaybackItemRead {
  return {
    id: "00000000-0000-4000-8000-000000000010",
    entry_id: "00000000-0000-4000-8000-000000000001",
    episode_id: "00000000-0000-4000-8000-000000000020",
    movie_title_id: null,
    position_in_entry: 1,
    absolute_position: 7,
    availability: "in_library",
    jellyfin_item_id: "00000000-0000-4000-8000-000000000030",
    order_type: "dvd",
    order_label: "Season 2 · Episode 1",
    covers_range: false,
    ...overrides,
  };
}
