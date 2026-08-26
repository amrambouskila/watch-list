import type { ReactElement } from "react";

const ESCALATED_STATE = "escalated";
const FAILED_STATE = "failed";

interface ToolChipProps {
  readonly name: string;
  readonly detail: string;
  readonly state: string;
}

function chipClass(state: string): string {
  if (state === ESCALATED_STATE) return "tool-chip tool-chip--escalated";
  return state === FAILED_STATE ? "tool-chip tool-chip--alert" : "tool-chip";
}

/** A one-line record of a tool Claude ran, so the research is visible while it happens. */
export function ToolChip({ name, detail, state }: ToolChipProps): ReactElement {
  return (
    <span className={chipClass(state)}>
      <span className="tool-chip__name">{name}</span>
      <span className="tool-chip__detail">{detail}</span>
      {state !== "" && <span className="tool-chip__state">{state}</span>}
    </span>
  );
}
