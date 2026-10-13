import type { ResolutionState } from "../types/CuratedEntryRead";

const LABELS: Readonly<Record<ResolutionState, string>> = {
  unresolved: "Unresolved",
  auto: "Auto",
  confirmed: "Confirmed",
  rejected: "Rejected",
};

/** How a resolution state reads in the interface, as opposed to how the projection stores it. */
export function resolutionStateLabel(state: ResolutionState): string {
  return LABELS[state];
}
