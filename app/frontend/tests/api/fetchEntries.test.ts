import { expect, it } from "vitest";

import { fetchEntries } from "../../src/api/fetchEntries";
import { aCuratedEntryRead } from "../support/aCuratedEntryRead";
import { aFakeServer } from "../support/aFakeServer";

it("reads the category's entry overlay without changing the workbook endpoint", async () => {
  const server = aFakeServer();
  const entry = aCuratedEntryRead();
  server.answers("GET /api/categories/a%2Fb/entries", [entry]);
  expect(await fetchEntries("a/b")).toEqual([entry]);
  expect(server.requests[0]?.query).toBe("?limit=500&offset=0");
});
