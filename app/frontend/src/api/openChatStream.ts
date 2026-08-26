import type { ChatEvent } from "../types/ChatEvent";
import { ApiError } from "./ApiError";

const FRAME_SEPARATOR = "\n\n";
const DATA_PREFIX = "data: ";
const CHAT_EVENT_TYPES: readonly string[] = ["text", "tool", "proposal", "error", "done"];

interface ChatErrorBody {
  error?: string;
  message?: string;
}

function toEvent(frame: string): ChatEvent | null {
  const line = frame.split("\n").find((candidate) => candidate.startsWith(DATA_PREFIX));
  if (line === undefined) return null;
  const parsed: unknown = JSON.parse(line.slice(DATA_PREFIX.length));
  if (typeof parsed !== "object" || parsed === null || !("type" in parsed)) return null;
  if (typeof parsed.type !== "string" || !CHAT_EVENT_TYPES.includes(parsed.type)) return null;
  return parsed as ChatEvent;
}

/**
 * Stream one chat turn, calling `onEvent` per frame as it arrives.
 *
 * The response is chunked with no content-length, so it is read frame by frame through the body
 * reader — `response.json()` here would block until the turn ended and destroy the live output.
 */
export async function openChatStream(
  sessionId: string,
  text: string,
  signal: AbortSignal,
  onEvent: (event: ChatEvent) => void,
): Promise<void> {
  const response = await fetch(`/api/chat/sessions/${encodeURIComponent(sessionId)}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({ text }),
    signal,
  });

  if (!response.ok) {
    // A refusal carries no stream, so its body is an ordinary bounded JSON response.
    const body = (await response.json().catch(() => ({}))) as ChatErrorBody;
    throw new ApiError(
      response.status,
      body.error ?? "ChatStreamFailed",
      body.message ?? `Claude could not be reached (${response.status}).`,
    );
  }
  if (response.body === null) throw new ApiError(response.status, "ChatStreamFailed", "The chat stream sent no body.");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  for (;;) {
    const chunk = await reader.read();
    if (chunk.done) break;
    buffer += decoder.decode(chunk.value, { stream: true }).replaceAll("\r", "");
    let boundary = buffer.indexOf(FRAME_SEPARATOR);
    while (boundary !== -1) {
      const event = toEvent(buffer.slice(0, boundary));
      buffer = buffer.slice(boundary + FRAME_SEPARATOR.length);
      if (event !== null) onEvent(event);
      boundary = buffer.indexOf(FRAME_SEPARATOR);
    }
  }
}
