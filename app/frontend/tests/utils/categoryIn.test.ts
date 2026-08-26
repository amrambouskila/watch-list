import { describe, expect, it } from "vitest";

import type { CatalogListing } from "../../src/types/CatalogListing";
import { categoryIn } from "../../src/utils/categoryIn";
import { aCategoryDetail } from "../support/aCategoryDetail";

function listingOf(ids: readonly string[]): CatalogListing {
  return {
    categories: ids.map((id) => aCategoryDetail({ id, name: id.toUpperCase() })),
    unreadable: [],
    shadowed: [],
    library_dir: "a-library",
  };
}

describe("categoryIn", () => {
  it("finds the library's entry for an id", () => {
    expect(categoryIn(listingOf(["one", "two"]), "two")?.name).toBe("TWO");
  });

  it("has nothing to offer while the library has not been read", () => {
    expect(categoryIn(null, "two")).toBeNull();
  });

  it("has nothing to offer for an id the library does not list", () => {
    expect(categoryIn(listingOf(["one"]), "two")).toBeNull();
  });
});
