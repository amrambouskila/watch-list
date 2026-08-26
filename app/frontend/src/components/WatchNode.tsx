import type { ReactElement } from "react";

import { SKIPPED, WATCHED } from "../types/WatchStatus";
import { nextWatchStatus } from "../utils/nextWatchStatus";
import { statusLabel } from "../utils/statusLabel";

interface WatchNodeProps {
  readonly status: string;
  readonly choices: readonly string[];
  readonly title: string;
  readonly onCycle: (next: string) => void;
}

function Mark({ status }: { readonly status: string }): ReactElement | null {
  if (status === WATCHED) {
    return (
      <svg className="node__mark" viewBox="0 0 12 12" aria-hidden="true">
        <polyline points="2,6.5 4.8,9.2 10,3.2" />
      </svg>
    );
  }
  if (status === SKIPPED) {
    return (
      <svg className="node__mark" viewBox="0 0 12 12" aria-hidden="true">
        <line x1="2.5" y1="9.5" x2="9.5" y2="2.5" />
      </svg>
    );
  }
  return null;
}

/**
 * The status control sits directly on the route rail, so marking an entry and
 * seeing how far along the order you are are the same gesture.
 */
export function WatchNode({ status, choices, title, onCycle }: WatchNodeProps): ReactElement {
  const next = nextWatchStatus(status, choices);
  return (
    <button
      type="button"
      className="node"
      data-status={status}
      aria-label={`${title}: ${statusLabel(status)}. Mark ${statusLabel(next).toLowerCase()}.`}
      onClick={() => onCycle(next)}
    >
      <Mark status={status} />
    </button>
  );
}
