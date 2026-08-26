import type { ChatEvent } from "../../src/types/ChatEvent";
import { anSseFrame } from "../../tests/support/anSseFrame";
import { aProbeLibrary, type ProbeLibrary } from "./aProbeLibrary";

const OK = 200;
const CONFLICT = 409;
const NOT_FOUND = 404;
const A_SESSION_ID = "a-probe-session";
const CATALOG_PATH = "/api/categories";
const SESSIONS_PATH = "/api/chat/sessions";
const PROPOSALS_PATH = "/api/chat/proposals/";
const MESSAGES_SUFFIX = "/messages";

/** What the backend answers when the workbook a proposal would write is held open by Excel. */
export const A_REFUSED_WRITE = "A Long Watch Order.xlsx is open in Excel, so nothing was written.";

function jsonResponse(body: unknown, status: number = OK): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

/** The refusal the app turns into a toast, so the probe raises that toast the way the app does. */
function refusedWrite(): Response {
  return jsonResponse({ error: "WorkbookLockedError", message: A_REFUSED_WRITE }, CONFLICT);
}

/** The turn arrives frame by frame, exactly as the backend writes it, so the real reader parses it. */
function streamedTurn(turn: readonly ChatEvent[]): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const event of turn) controller.enqueue(encoder.encode(anSseFrame(event)));
      controller.close();
    },
  });
  return new Response(body, { status: OK, headers: { "Content-Type": "text/event-stream" } });
}

/**
 * The backend, standing in for the real one at the only boundary the app has: fetch.
 *
 * The probe answers here rather than over a socket so that a guard run needs no server, no
 * workbook and no model, and cannot reach any of them by accident.
 *
 * The library is an argument because three surfaces are about a library with something wrong in it,
 * and the app only ever learns that here.
 */
export function serveProbeBackend(turn: readonly ChatEvent[], library: ProbeLibrary = aProbeLibrary()): void {
  const { detail, listing } = library;

  window.fetch = (input: RequestInfo | URL): Promise<Response> => {
    const { pathname } = new URL(String(input), window.location.origin);
    if (pathname === CATALOG_PATH) return Promise.resolve(jsonResponse(listing));
    if (pathname === `${CATALOG_PATH}/${detail.id}`) return Promise.resolve(jsonResponse(detail));
    if (pathname === SESSIONS_PATH) return Promise.resolve(jsonResponse({ session_id: A_SESSION_ID }));
    if (pathname.endsWith(MESSAGES_SUFFIX)) return Promise.resolve(streamedTurn(turn));
    if (pathname.startsWith(PROPOSALS_PATH)) return Promise.resolve(refusedWrite());
    return Promise.resolve(new Response(null, { status: NOT_FOUND }));
  };
}
