import { describe, expect, it } from "vitest";

import { requestPages } from "../../src/api/requestPages";
import { aFakeServer } from "../support/aFakeServer";

describe("requestPages", () => {
  it.each([0, 500, 501])("returns all %i rows in server order, ending at the first short page", async (count) => {
    const server = aFakeServer();
    const rows = Array.from({ length: count }, (_, index) => index);
    server.handles("GET /items", (asked) => {
      const offset = Number(new URLSearchParams(asked.query).get("offset"));
      return { status: 200, body: rows.slice(offset, offset + 500) };
    });
    expect(await requestPages<number>("/items")).toEqual(rows);
    expect(server.requests.map((asked) => asked.query)).toEqual(
      count < 500 ? ["?limit=500&offset=0"] : ["?limit=500&offset=0", "?limit=500&offset=500"],
    );
  });

  it("rejects a failed later page instead of returning a truncated list", async () => {
    const server = aFakeServer();
    server.handles("GET /items", (asked) => asked.query.endsWith("offset=0")
      ? { status: 200, body: Array.from({ length: 500 }, (_, index) => index) }
      : { status: 503, body: { message: "Page unavailable" } });
    await expect(requestPages<number>("/items")).rejects.toThrow("Page unavailable");
  });

  it("does not fetch another page after cancellation", async () => {
    const server = aFakeServer();
    const abort = new AbortController();
    server.handles("GET /items", () => {
      abort.abort();
      return { status: 200, body: Array.from({ length: 500 }, (_, index) => index) };
    });
    await expect(requestPages<number>("/items", abort.signal)).rejects.toMatchObject({ name: "AbortError" });
    expect(server.requests).toHaveLength(1);
  });
});
