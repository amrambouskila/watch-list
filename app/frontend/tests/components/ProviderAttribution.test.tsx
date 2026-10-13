import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { act, render, screen, within } from "@testing-library/react";
import type { ReactElement } from "react";
import { Provider } from "react-redux";
import { describe, expect, it, vi } from "vitest";

import { ProviderAttribution } from "../../src/components/ProviderAttribution";
import { Sidebar } from "../../src/components/Sidebar";
import { App } from "../../src/App";
import { selectCategory } from "../../src/stores/uiSlice";
import { aTestStore, type TestStore } from "../support/aTestStore";

/**
 * The words, carried here rather than imported from the component.
 *
 * Both are licence text — TMDB's API Terms section 3 and TheTVDB's published sample — so the test
 * has to fail when they drift. Importing the component's own constants would only prove it renders
 * whatever it currently says.
 */
const TMDB_NOTICE =
  "This product uses TMDB and the TMDB APIs but is not endorsed, certified, or otherwise approved by TMDB.";
const TVDB_NOTICE = "Metadata provided by TheTVDB. Please consider adding missing information or subscribing.";
const TMDB_URL = "https://www.themoviedb.org";
const TVDB_URL = "https://thetvdb.com";
const TMDB_LINK = "TMDB";
const TVDB_LINK = "thetvdb.com";
const LOGO_SRC = "/tmdb-logo.svg";
const NEW_TAB = "_blank";
const NEW_TAB_REL = "noopener noreferrer";
/** Vitest runs from the frontend project root, and the mark is served straight out of `public/`. */
const LOGO_FILE = resolve(process.cwd(), "public", "tmdb-logo.svg");
/** Small enough that the sidebar foot is not paying for it; TMDB's own file is about a tenth of this. */
const LOGO_SIZE_CAP_BYTES = 20_000;
const A_CATEGORY_ID = "a-category";

/** The app asks the backend for the library the moment it mounts; nothing here is about that answer. */
function withNoBackend(): void {
  vi.stubGlobal("fetch", () => new Promise<Response>(() => undefined));
}

function inAStore(tree: ReactElement, store: TestStore = aTestStore()): TestStore {
  render(<Provider store={store}>{tree}</Provider>);
  return store;
}

describe("ProviderAttribution", () => {
  it("renders the TMDB notice verbatim", () => {
    render(<ProviderAttribution />);

    expect(screen.getByText(TMDB_NOTICE)).toBeInTheDocument();
  });

  it("renders TheTVDB's sample text verbatim", () => {
    render(<ProviderAttribution />);

    expect(screen.getByText(TVDB_NOTICE)).toBeInTheDocument();
  });

  it("links the unmodified TMDB mark to themoviedb.org", () => {
    render(<ProviderAttribution />);

    const logo = screen.getByAltText(TMDB_LINK);
    expect(logo).toHaveAttribute("src", LOGO_SRC);
    expect(logo.closest("a")).toHaveAttribute("href", TMDB_URL);
  });

  it("links TheTVDB's notice to thetvdb.com", () => {
    render(<ProviderAttribution />);

    expect(screen.getByRole("link", { name: TVDB_LINK })).toHaveAttribute("href", TVDB_URL);
  });

  it.each([
    ["the TMDB mark", TMDB_LINK],
    ["TheTVDB's link", TVDB_LINK],
  ])("opens %s in a new tab that cannot reach back", (_case, name) => {
    render(<ProviderAttribution />);

    const link = screen.getByRole("link", { name });
    expect(link).toHaveAttribute("target", NEW_TAB);
    expect(link).toHaveAttribute("rel", NEW_TAB_REL);
  });

  it("names both links, so neither is reachable only by its markup", () => {
    render(<ProviderAttribution />);

    expect(screen.getAllByRole("link").map((link) => link.textContent?.trim() || link.getAttribute("aria-label"))).toEqual(
      [TMDB_LINK, TVDB_LINK],
    );
  });
});

describe("the TMDB mark on disk", () => {
  it("is the file the component names, and is not a document that could run anything", () => {
    const svg = readFileSync(LOGO_FILE, "utf8");

    expect(svg.length).toBeLessThan(LOGO_SIZE_CAP_BYTES);
    expect(svg).toContain("<svg");
    expect(svg).not.toContain("<script");
  });
});

describe("the sidebar foot", () => {
  it("carries both providers' attribution", () => {
    inAStore(<Sidebar />);

    const sidebar = screen.getByRole("navigation", { name: "Watch order library" });
    expect(within(sidebar).getByText(TMDB_NOTICE)).toBeInTheDocument();
    expect(within(sidebar).getByText(TVDB_NOTICE)).toBeInTheDocument();
  });

  it("keeps the marks under this app's own wordmark, which is what TMDB's terms ask for", () => {
    inAStore(<Sidebar />);

    const wordmark = screen.getByRole("button", { name: "Watch List" });
    const mark = screen.getByAltText(TMDB_LINK);
    expect(wordmark.compareDocumentPosition(mark) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it.each([
    ["the cards wall", null],
    ["an open category", A_CATEGORY_ID],
  ])("is on screen on %s", (_case, categoryId) => {
    withNoBackend();
    const store = inAStore(<App />);
    if (categoryId !== null) act(() => void store.dispatch(selectCategory(categoryId)));

    expect(store.getState().ui.view).toBe(categoryId === null ? "home" : "category");
    expect(screen.getByText(TMDB_NOTICE)).toBeInTheDocument();
    expect(screen.getByText(TVDB_NOTICE)).toBeInTheDocument();
  });
});
