/** A response body the test feeds by hand, so a frame can be split exactly where a chunk would split it. */
export interface EventStream {
  readonly body: ReadableStream<Uint8Array>;
  push(text: string): void;
  close(): void;
  fail(error: Error): void;
}

export function anEventStream(): EventStream {
  const encoder = new TextEncoder();
  let sink: ReadableStreamDefaultController<Uint8Array> | null = null;
  let finished = false;
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      sink = controller;
    },
  });

  return {
    body,
    push(text) {
      if (!finished) sink?.enqueue(encoder.encode(text));
    },
    close() {
      if (finished) return;
      finished = true;
      sink?.close();
    },
    fail(error) {
      if (finished) return;
      finished = true;
      sink?.error(error);
    },
  };
}
