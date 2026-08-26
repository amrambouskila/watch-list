import { vi } from "vitest";

import type { EventStream } from "./anEventStream";

export interface RecordedRequest {
  readonly method: string;
  readonly path: string;
  readonly query: string;
  readonly body: unknown;
}

export interface Reply {
  readonly status: number;
  readonly body: unknown;
}

type Responder = (request: RecordedRequest) => Reply | Promise<Reply>;

/** Not a status the app can see in life: it means a test asked for a route nobody is serving. */
const NO_SUCH_ROUTE = 599;
const OK = 200;
const NO_CONTENT = 204;

export interface FakeServer {
  readonly requests: readonly RecordedRequest[];
  answers(route: string, body: unknown): void;
  refuses(route: string, status: number, body: unknown): void;
  handles(route: string, responder: Responder): void;
  streams(route: string, stream: EventStream): void;
  requestsFor(route: string): RecordedRequest[];
}

function responseFor(reply: Reply): Response {
  if (reply.status === NO_CONTENT) return new Response(null, { status: NO_CONTENT });
  return new Response(JSON.stringify(reply.body), {
    status: reply.status,
    headers: { "Content-Type": "application/json" },
  });
}

function sentBody(init: RequestInit | undefined): unknown {
  return typeof init?.body === "string" ? JSON.parse(init.body) : null;
}

/**
 * The backend, standing in for the real one at the only boundary the app has: fetch.
 *
 * Every request is recorded, so a test can say what the app asked the server to do rather than
 * what it asked some intermediate module to do.
 */
export function aFakeServer(): FakeServer {
  const requests: RecordedRequest[] = [];
  const responders = new Map<string, Responder>();
  const bodies = new Map<string, EventStream>();

  const serve = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = new URL(String(input), "http://localhost");
    const request: RecordedRequest = {
      method: (init?.method ?? "GET").toUpperCase(),
      path: url.pathname,
      query: url.search,
      body: sentBody(init),
    };
    requests.push(request);

    const route = `${request.method} ${request.path}`;
    const stream = bodies.get(route);
    if (stream !== undefined) {
      init?.signal?.addEventListener("abort", () => {
        stream.fail(new DOMException("The connection was closed", "AbortError"));
      });
      return new Response(stream.body, { status: OK });
    }

    const responder = responders.get(route);
    if (responder === undefined) {
      return responseFor({ status: NO_SUCH_ROUTE, body: { error: "NoSuchRoute", message: `nothing serves ${route}` } });
    }
    return responseFor(await responder(request));
  };

  vi.stubGlobal("fetch", serve);

  return {
    requests,
    answers(route, body) {
      responders.set(route, () => ({ status: OK, body }));
    },
    refuses(route, status, body) {
      responders.set(route, () => ({ status, body }));
    },
    handles(route, responder) {
      responders.set(route, responder);
    },
    streams(route, stream) {
      bodies.set(route, stream);
    },
    requestsFor(route) {
      return requests.filter((request) => `${request.method} ${request.path}` === route);
    },
  };
}
