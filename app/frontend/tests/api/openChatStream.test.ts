import { beforeEach, describe, expect, it } from "vitest";

import { ApiError } from "../../src/api/ApiError";
import { openChatStream } from "../../src/api/openChatStream";
import type { ChatEvent } from "../../src/types/ChatEvent";
import { aFakeServer, type FakeServer } from "../support/aFakeServer";
import { anEventStream, type EventStream } from "../support/anEventStream";
import { anSseFrame } from "../support/anSseFrame";

const SESSION = "a-session";
const SEND_ROUTE = `POST /api/chat/sessions/${SESSION}/messages`;

let server: FakeServer;
let stream: EventStream;
let received: ChatEvent[];

/** Start the read, then feed the body: the reader must survive whatever order the bytes arrive in. */
function startReading(): Promise<void> {
  return openChatStream(SESSION, "a question", new AbortController().signal, (event) => received.push(event));
}

beforeEach(() => {
  server = aFakeServer();
  stream = anEventStream();
  received = [];
  server.streams(SEND_ROUTE, stream);
});

describe("openChatStream", () => {
  it("delivers each frame in the order the server wrote it", async () => {
    const reading = startReading();
    stream.push(anSseFrame({ type: "text", text: "first" }));
    stream.push(anSseFrame({ type: "done", total_cost_usd: 0.02 }));
    stream.close();

    await reading;

    expect(received).toEqual([
      { type: "text", text: "first" },
      { type: "done", total_cost_usd: 0.02 },
    ]);
  });

  it("reassembles a frame that the network split down the middle", async () => {
    const whole = anSseFrame({ type: "text", text: "a sentence that arrived in pieces" });
    const reading = startReading();
    stream.push(whole.slice(0, 12));
    stream.push(whole.slice(12, 30));
    stream.push(whole.slice(30));
    stream.close();

    await reading;

    expect(received).toEqual([{ type: "text", text: "a sentence that arrived in pieces" }]);
  });

  it("splits several frames that arrived in one chunk", async () => {
    const reading = startReading();
    stream.push(anSseFrame({ type: "text", text: "one" }) + anSseFrame({ type: "text", text: "two" }));
    stream.close();

    await reading;

    expect(received.map((event) => event.text)).toEqual(["one", "two"]);
  });

  it("reads frames the server ended with carriage returns", async () => {
    const reading = startReading();
    stream.push(`data: ${JSON.stringify({ type: "text", text: "windows" })}\r\n\r\n`);
    stream.close();

    await reading;

    expect(received).toEqual([{ type: "text", text: "windows" }]);
  });

  it("ignores the lines of a frame that are not its data", async () => {
    const reading = startReading();
    stream.push(`event: message\nid: 7\ndata: ${JSON.stringify({ type: "text", text: "kept" })}\n\n`);
    stream.close();

    await reading;

    expect(received).toEqual([{ type: "text", text: "kept" }]);
  });

  it("drops a frame carrying no data line, such as a keep-alive comment", async () => {
    const reading = startReading();
    stream.push(": keeping the connection open\n\n");
    stream.push(anSseFrame({ type: "text", text: "kept" }));
    stream.close();

    await reading;

    expect(received).toEqual([{ type: "text", text: "kept" }]);
  });

  it("drops a frame of a type this build does not know, rather than passing it on", async () => {
    const reading = startReading();
    stream.push(anSseFrame({ type: "some-later-version-of-the-backend", text: "ignored" }));
    stream.push(anSseFrame({ type: "text", text: "kept" }));
    stream.close();

    await reading;

    expect(received).toEqual([{ type: "text", text: "kept" }]);
  });

  it("drops a frame whose data is not an object with a type", async () => {
    const reading = startReading();
    stream.push(anSseFrame(["not", "an", "event"]));
    stream.push(anSseFrame(null));
    stream.push(anSseFrame({ text: "no type at all" }));
    stream.push(anSseFrame({ type: "text", text: "kept" }));
    stream.close();

    await reading;

    expect(received).toEqual([{ type: "text", text: "kept" }]);
  });

  it("does not deliver a frame the stream ended in the middle of", async () => {
    const reading = startReading();
    stream.push(`data: ${JSON.stringify({ type: "text", text: "cut off" })}`);
    stream.close();

    await reading;

    expect(received).toEqual([]);
  });

  it("stops reading when the turn is aborted, keeping what already arrived", async () => {
    const aborter = new AbortController();
    const reading = openChatStream(SESSION, "a question", aborter.signal, (event) => received.push(event));
    stream.push(anSseFrame({ type: "text", text: "before the stop" }));
    await Promise.resolve();
    aborter.abort();

    await expect(reading).rejects.toThrow();
    expect(received).toEqual([{ type: "text", text: "before the stop" }]);
  });

  it("refuses to read a stream the server accepted but sent no body for", async () => {
    server = aFakeServer();
    server.handles(SEND_ROUTE, () => ({ status: 200, body: undefined }));

    await expect(startReading()).rejects.toMatchObject({
      name: "ApiError",
      code: "ChatStreamFailed",
      message: "The chat stream sent no body.",
    });
  });

  it("reports the server's own reason when the turn is refused outright", async () => {
    server = aFakeServer();
    server.refuses(SEND_ROUTE, 409, { error: "ChatBusy", message: "That session is already answering." });

    await expect(startReading()).rejects.toThrow(
      new ApiError(409, "ChatBusy", "That session is already answering."),
    );
  });

  it("still names the failure when the refusal carries no readable body", async () => {
    server = aFakeServer();
    server.handles(SEND_ROUTE, () => ({ status: 502, body: undefined }));

    await expect(startReading()).rejects.toMatchObject({
      name: "ApiError",
      code: "ChatStreamFailed",
      message: "Claude could not be reached (502).",
    });
  });
});
