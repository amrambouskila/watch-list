import type { Availability } from "../../src/types/Availability";
import { aCuratedEntryRead } from "../../tests/support/aCuratedEntryRead";
import { aPlaybackItemRead } from "../../tests/support/aPlaybackItemRead";
import { aProbeLibrary, type ProbeLibrary } from "./aProbeLibrary";

/** Distinct row states, and separate episode slots that can share one local file. */
export function aPlayableCategory(): ProbeLibrary {
  const library = aProbeLibrary();
  const states: readonly Availability[] = ["in_library", "ambiguous", "not_in_library"];
  const entries = library.detail.rows.slice(0, states.length).map((row, index) => ({
    ...aCuratedEntryRead({
      id: `00000000-0000-4000-8000-${String(index + 1).padStart(12, "0")}`,
      categorySlug: library.detail.id, position: index + 1, cells: row.cells, state: "confirmed",
    }),
    availability: states[index] ?? "not_in_library",
    jellyfin_item_id: index === 0 ? "00000000-0000-4000-8000-000000000099" : null,
  }));
  return {
    ...library, entries,
    playbackItems: [
      aPlaybackItemRead({ covers_range: true }),
      aPlaybackItemRead({ id: "second-slot", position_in_entry: 2, order_label: "Season 2 · Episode 2", covers_range: true }),
      aPlaybackItemRead({ id: "missing-slot", position_in_entry: 3, order_label: "Season 2 · Episode 3", availability: "not_in_library", jellyfin_item_id: null }),
    ],
  };
}
