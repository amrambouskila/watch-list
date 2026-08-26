import { describe, expect, it } from "vitest";

import { enqueueWrite, noteMtime } from "../../src/stores/writeQueue";

/** Each test uses a workbook of its own: the queue is module state that outlives one test. */
let workbooks = 0;

function aWorkbook(): string {
  workbooks += 1;
  return `workbook-${workbooks}`;
}

describe("writeQueue", () => {
  it("threads each response's stamp into the write behind it, so a quick second click is not a conflict", async () => {
    const workbook = aWorkbook();
    const sent: number[] = [];

    const first = enqueueWrite(workbook, 1, (mtime) => {
      sent.push(mtime);
      return Promise.resolve({ mtime: 2 });
    });
    const second = enqueueWrite(workbook, 1, (mtime) => {
      sent.push(mtime);
      return Promise.resolve({ mtime: 3 });
    });
    await Promise.all([first, second]);

    expect(sent).toEqual([1, 2]);
  });

  it("runs the writes to one workbook one after another rather than at once", async () => {
    const workbook = aWorkbook();
    const order: string[] = [];
    let releaseFirst = (): void => undefined;
    const held = new Promise<void>((resolve) => {
      releaseFirst = resolve;
    });

    const first = enqueueWrite(workbook, 1, async () => {
      order.push("first started");
      await held;
      order.push("first finished");
      return { mtime: 2 };
    });
    const second = enqueueWrite(workbook, 1, () => {
      order.push("second started");
      return Promise.resolve({ mtime: 3 });
    });

    releaseFirst();
    await Promise.all([first, second]);

    expect(order).toEqual(["first started", "first finished", "second started"]);
  });

  it("does not make a write to one workbook wait on a write to another", async () => {
    const held = aWorkbook();
    const free = aWorkbook();
    let releaseHeld = (): void => undefined;
    const blocked = new Promise<void>((resolve) => {
      releaseHeld = resolve;
    });

    const slow = enqueueWrite(held, 1, async () => {
      await blocked;
      return { mtime: 2 };
    });
    const quick = await enqueueWrite(free, 7, (mtime) => Promise.resolve({ mtime }));

    expect(quick.mtime).toBe(7);

    releaseHeld();
    await slow;
  });

  it("lets the write behind a failed one still run", async () => {
    const workbook = aWorkbook();
    const sent: number[] = [];

    const refused = enqueueWrite(workbook, 1, () => Promise.reject(new Error("The server refused that change.")));
    const next = enqueueWrite(workbook, 1, (mtime) => {
      sent.push(mtime);
      return Promise.resolve({ mtime: 4 });
    });

    await expect(refused).rejects.toThrow("The server refused that change.");
    await next;

    expect(sent).toEqual([1]);
  });

  it("sends the freshest stamp it was told about rather than the one the click was made against", async () => {
    const workbook = aWorkbook();
    const sent: number[] = [];

    noteMtime(workbook, 9);
    await enqueueWrite(workbook, 1, (mtime) => {
      sent.push(mtime);
      return Promise.resolve({ mtime: 9 });
    });

    expect(sent).toEqual([9]);
  });
});
