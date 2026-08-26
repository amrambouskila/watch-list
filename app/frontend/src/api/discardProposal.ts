import { ApiError } from "./ApiError";

/**
 * Discard a chat session along with any proposal still pending on it.
 *
 * A proposal is held by its session and has no endpoint of its own, so ending the session is how
 * the server is told to forget one. It answers 204, which `request` cannot parse.
 */
export async function discardProposal(sessionId: string): Promise<void> {
  const response = await fetch(`/api/chat/sessions/${encodeURIComponent(sessionId)}`, { method: "DELETE" });
  if (!response.ok) {
    throw new ApiError(response.status, "DiscardFailed", `That chat session was not closed (${response.status}).`);
  }
}
