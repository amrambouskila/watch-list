import { describe, expect, it } from "vitest";

import { isHttpUrl } from "../../src/utils/isHttpUrl";

describe("isHttpUrl", () => {
  it.each(["https://example.org/a.jpg", "http://example.org/a.jpg"])("accepts %s", (value) => {
    expect(isHttpUrl(value)).toBe(true);
  });

  it.each([
    ["a relative path the backend serves", "/heroes/a-category.png"],
    ["a bare host", "example.org/a.jpg"],
    ["prose the model wrote instead of a link", "I could not find a source for this"],
    ["a scheme that would run script", "javascript:alert(1)"],
    ["an inline payload", "data:image/png;base64,AAAA"],
    ["a protocol-relative address", "//example.org/a.jpg"],
    ["nothing at all", ""],
  ])("rejects %s", (_case, value) => {
    expect(isHttpUrl(value)).toBe(false);
  });

  it("matches on the scheme rather than anywhere in the string", () => {
    expect(isHttpUrl("see https://example.org for the licence")).toBe(false);
  });
});
