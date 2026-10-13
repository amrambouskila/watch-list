import type { ReactElement } from "react";

import type { Availability } from "../types/Availability";

const LABELS: Record<Availability, string> = {
  in_library: "In library",
  not_in_library: "Opens on your subscription",
  ambiguous: "Needs a pick",
};
const MARKS: Record<Availability, string> = {
  in_library: "M3 8l3 3 7-7",
  not_in_library: "M3 12L12 3M5 3h7v7",
  ambiguous: "M6 5a2 2 0 114 0c0 2-2 2-2 4M8 12v1",
};

export function AvailabilityBadge({ availability }: { readonly availability: Availability }): ReactElement {
  return (
    <span className="availability" data-availability={availability}>
      <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
        <path d={MARKS[availability]} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
      {LABELS[availability]}
    </span>
  );
}
