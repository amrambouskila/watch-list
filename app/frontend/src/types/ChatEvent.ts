import type { Proposal } from "./Proposal";

export type ChatEventType = "text" | "tool" | "proposal" | "error" | "done";

/** One SSE frame. Only the fields the frame's type uses are populated. */
export interface ChatEvent {
  type: ChatEventType;
  text?: string | null;
  name?: string | null;
  detail?: string | null;
  state?: string | null;
  proposal?: Proposal | null;
  code?: string | null;
  message?: string | null;
  turns?: number | null;
  total_cost_usd?: number | null;
}
