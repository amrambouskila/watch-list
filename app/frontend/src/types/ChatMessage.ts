export type ChatMessageRole = "you" | "claude" | "tool" | "note" | "error";

export interface ChatMessage {
  id: string;
  role: ChatMessageRole;
  /** Prose for a spoken entry; the tool's detail line for a tool entry. */
  text: string;
  /** Tool entries only: which tool ran, and the state it reported. */
  tool: string;
  state: string;
}
