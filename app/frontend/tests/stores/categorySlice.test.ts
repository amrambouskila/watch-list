import { beforeEach, describe, expect, it } from "vitest";

import {
  clear,
  enableWatchColumn,
  loadCategory,
  removeRow,
  renameWorkbook,
  retireWorkbook,
  writeRow,
} from "../../src/stores/categorySlice";
import { applyProposal } from "../../src/stores/chatSlice";
import { selectCategory, toggleRow } from "../../src/stores/uiSlice";
import type { CatalogListing } from "../../src/types/CatalogListing";
import type { CategoryDetail } from "../../src/types/CategoryDetail";
import { aCategoryDetail } from "../support/aCategoryDetail";
import { aFakeServer, type FakeServer } from "../support/aFakeServer";
import { aTestStore, type TestStore } from "../support/aTestStore";

const STALE = { error: "StaleWorkbookError", message: "That workbook changed underneath you." };
const REFUSED = { error: "WorkbookLockedError", message: "That workbook is open in Excel." };
const AS_WRITTEN = "as written";

/** Each test writes to a workbook of its own: the write queue is module state that outlives one test. */
let categories = 0;

function aCategoryId(): string {
  categories += 1;
  return `category-${categories}`;
}

let server: FakeServer;
let store: TestStore;

function twoRows(id: string, mtime: number, secondNote = AS_WRITTEN, thirdNote = AS_WRITTEN): CategoryDetail {
  return aCategoryDetail({
    id,
    mtime,
    rows: [
      { row: 2, cells: { title: "The Second", note: secondNote } },
      { row: 3, cells: { title: "The Third", note: thirdNote } },
    ],
  });
}

async function openCategory(detail: CategoryDetail): Promise<void> {
  server.answers(`GET /api/categories/${detail.id}`, detail);
  store.dispatch(selectCategory(detail.id));
  await store.dispatch(loadCategory(detail.id));
}

function noteOf(row: number): string | undefined {
  return store.getState().category.detail?.rows.find((entry) => entry.row === row)?.cells["note"];
}

function toastTones(): string[] {
  return store.getState().ui.toasts.map((toast) => `${toast.tone}: ${toast.message}`);
}

beforeEach(() => {
  server = aFakeServer();
  store = aTestStore();
});

describe("categorySlice opening a category", () => {
  it("paints the rows the workbook holds", async () => {
    const id = aCategoryId();

    await openCategory(twoRows(id, 1));

    expect(store.getState().category.status).toBe("ready");
    expect(noteOf(2)).toBe(AS_WRITTEN);
  });

  it("says why a category could not be opened and paints nothing", async () => {
    const id = aCategoryId();
    server.refuses(`GET /api/categories/${id}`, 422, { error: "UnreadableWorkbook", message: "That sheet has no header." });

    await store.dispatch(loadCategory(id));

    expect(store.getState().category).toMatchObject({ detail: null, status: "failed" });
    expect(toastTones()).toEqual(["error: That sheet has no header."]);
  });

  it("does not blank the category on screen when a different one fails to open", async () => {
    const open = aCategoryId();
    const other = aCategoryId();
    await openCategory(twoRows(open, 1));
    server.refuses(`GET /api/categories/${other}`, 404, { error: "NoSuchCategory", message: "No such category." });

    await store.dispatch(loadCategory(other));

    expect(store.getState().category.detail?.id).toBe(open);
  });

  it("ignores a reply that describes a category other than the one that was asked for", async () => {
    const asked = aCategoryId();
    const answered = aCategoryId();
    server.answers(`GET /api/categories/${asked}`, twoRows(answered, 1));

    await store.dispatch(loadCategory(asked));

    expect(store.getState().category.detail).toBeNull();
  });

  it("takes the rows off the screen when the category is left", async () => {
    const id = aCategoryId();
    await openCategory(twoRows(id, 1));

    store.dispatch(clear());

    expect(store.getState().category).toEqual({ detail: null, status: "idle", pending: {} });
  });
});

describe("categorySlice editing a row", () => {
  it("paints an edit before the server has confirmed it", async () => {
    const id = aCategoryId();
    await openCategory(twoRows(id, 1));
    server.answers(`PATCH /api/categories/${id}/rows/2`, twoRows(id, 2, "edited"));

    const run = store.dispatch(
      writeRow({ categoryId: id, row: 2, cells: { note: "edited" }, previous: { note: AS_WRITTEN } }),
    );
    expect(noteOf(2)).toBe("edited");

    await run;
    expect(noteOf(2)).toBe("edited");
  });

  it("sends the stamp the app last saw with the edit", async () => {
    const id = aCategoryId();
    await openCategory(twoRows(id, 41));
    server.answers(`PATCH /api/categories/${id}/rows/2`, twoRows(id, 42, "edited"));

    await store.dispatch(
      writeRow({ categoryId: id, row: 2, cells: { note: "edited" }, previous: { note: AS_WRITTEN } }),
    );

    expect(server.requestsFor(`PATCH /api/categories/${id}/rows/2`)[0]?.body).toEqual({
      cells: { note: "edited" },
      expected_mtime: 41,
    });
  });

  it("puts back what the sheet held when the edit is refused", async () => {
    const id = aCategoryId();
    await openCategory(twoRows(id, 1));
    server.refuses(`PATCH /api/categories/${id}/rows/2`, 423, REFUSED);

    await store.dispatch(
      writeRow({ categoryId: id, row: 2, cells: { note: "edited" }, previous: { note: AS_WRITTEN } }),
    );

    expect(noteOf(2)).toBe(AS_WRITTEN);
    expect(toastTones()).toEqual([`error: ${REFUSED.message}`]);
  });

  it("repaints from the workbook, not from the click, when the workbook changed underneath the edit", async () => {
    const id = aCategoryId();
    await openCategory(twoRows(id, 1));
    server.refuses(`PATCH /api/categories/${id}/rows/2`, 409, STALE);
    server.answers(`GET /api/categories/${id}`, twoRows(id, 2, "what the owner typed in Excel"));

    await store.dispatch(
      writeRow({ categoryId: id, row: 2, cells: { note: "edited" }, previous: { note: AS_WRITTEN } }),
    );

    expect(noteOf(2)).toBe("what the owner typed in Excel");
    expect(toastTones()).toEqual([`info: ${STALE.message}`]);
  });

  it("keeps a later edit on screen while an earlier one is still being confirmed", async () => {
    const id = aCategoryId();
    await openCategory(twoRows(id, 1));
    server.answers(`PATCH /api/categories/${id}/rows/2`, twoRows(id, 2, "edited second"));
    server.answers(`PATCH /api/categories/${id}/rows/3`, twoRows(id, 3, "edited second", "edited third"));

    const first = store.dispatch(
      writeRow({ categoryId: id, row: 2, cells: { note: "edited second" }, previous: { note: AS_WRITTEN } }),
    );
    const second = store.dispatch(
      writeRow({ categoryId: id, row: 3, cells: { note: "edited third" }, previous: { note: AS_WRITTEN } }),
    );

    await first;
    expect(noteOf(3)).toBe("edited third");

    await second;
    expect(noteOf(3)).toBe("edited third");
  });

  it("repaints from the workbook when a row could not be deleted because the workbook changed", async () => {
    const id = aCategoryId();
    await openCategory(twoRows(id, 1));
    server.refuses(`DELETE /api/categories/${id}/rows/3`, 409, STALE);
    server.answers(`GET /api/categories/${id}`, twoRows(id, 2, AS_WRITTEN, "what the owner typed in Excel"));

    await store.dispatch(removeRow({ categoryId: id, row: 3 }));

    expect(noteOf(3)).toBe("what the owner typed in Excel");
  });

  it("closes the expanded row once a deletion lands, since the numbers below it have shifted", async () => {
    const id = aCategoryId();
    await openCategory(twoRows(id, 1));
    server.answers(`DELETE /api/categories/${id}/rows/3`, aCategoryDetail({ id, mtime: 2, rows: [] }));
    store.dispatch(toggleRow(3));

    await store.dispatch(removeRow({ categoryId: id, row: 3 }));

    expect(store.getState().ui.expandedRow).toBeNull();
  });

  it("refuses to write to a category that is no longer open, before anything reaches the server", async () => {
    const id = aCategoryId();

    await store.dispatch(enableWatchColumn({ categoryId: id }));

    expect(server.requests).toEqual([]);
    expect(toastTones()).toEqual(["error: That category is no longer open."]);
  });
});

describe("categorySlice applying an approved proposal", () => {
  it("repaints the open category with what was written to it", async () => {
    const id = aCategoryId();
    await openCategory(twoRows(id, 1));
    server.answers("POST /api/chat/proposals/a-proposal/approve", twoRows(id, 2, "written by Claude"));

    await store.dispatch(applyProposal("a-proposal"));

    expect(noteOf(2)).toBe("written by Claude");
    expect(store.getState().category.detail?.mtime).toBe(2);
    expect(store.getState().category.status).toBe("ready");
  });

  it("leaves the open category alone when the proposal was written to a different one", async () => {
    const open = aCategoryId();
    const other = aCategoryId();
    await openCategory(twoRows(open, 1));
    server.answers("POST /api/chat/proposals/a-proposal/approve", twoRows(other, 2, "written by Claude"));

    await store.dispatch(applyProposal("a-proposal"));

    expect(store.getState().category.detail?.id).toBe(open);
    expect(noteOf(2)).toBe(AS_WRITTEN);
  });

  it("sends the stamp the approved write produced with the next edit, not the one it spent", async () => {
    const id = aCategoryId();
    await openCategory(twoRows(id, 1));
    server.answers("POST /api/chat/proposals/a-proposal/approve", twoRows(id, 77, "written by Claude"));
    server.answers(`PATCH /api/categories/${id}/rows/2`, twoRows(id, 78, "edited"));

    await store.dispatch(applyProposal("a-proposal"));
    await store.dispatch(
      writeRow({ categoryId: id, row: 2, cells: { note: "edited" }, previous: { note: "written by Claude" } }),
    );

    expect(server.requestsFor(`PATCH /api/categories/${id}/rows/2`)[0]?.body).toMatchObject({ expected_mtime: 77 });
  });
});

describe("categorySlice renaming and retiring", () => {
  it("carries the selection to the id the new filename derives", async () => {
    const id = aCategoryId();
    const renamed = aCategoryId();
    await openCategory(twoRows(id, 1));
    server.answers(`POST /api/categories/${id}/rename`, aCategoryDetail({ id: renamed, name: "Renamed", mtime: 2 }));

    await store.dispatch(renameWorkbook({ categoryId: id, stem: "Renamed" }));

    expect(store.getState().category.detail?.id).toBe(renamed);
    expect(store.getState().ui.activeCategoryId).toBe(renamed);
  });

  it("sends the stamp the rename produced with the next write to the renamed workbook", async () => {
    const id = aCategoryId();
    const renamed = aCategoryId();
    await openCategory(twoRows(id, 1));
    server.answers(`POST /api/categories/${id}/rename`, twoRows(renamed, 55));
    server.answers(`PATCH /api/categories/${renamed}/rows/2`, twoRows(renamed, 56, "edited"));

    await store.dispatch(renameWorkbook({ categoryId: id, stem: "Renamed" }));
    await store.dispatch(
      writeRow({ categoryId: renamed, row: 2, cells: { note: "edited" }, previous: { note: AS_WRITTEN } }),
    );

    expect(server.requestsFor(`PATCH /api/categories/${renamed}/rows/2`)[0]?.body).toMatchObject({
      expected_mtime: 55,
    });
  });

  it("takes the retired category off the screen and keeps the library the move left behind", async () => {
    const id = aCategoryId();
    const left: CatalogListing = { categories: [], unreadable: [], shadowed: [], library_dir: "a-library" };
    await openCategory(twoRows(id, 1));
    server.answers(`DELETE /api/categories/${id}`, left);

    await store.dispatch(retireWorkbook({ categoryId: id }));

    expect(store.getState().category.detail).toBeNull();
    expect(store.getState().catalog.listing).toEqual(left);
    expect(store.getState().ui).toMatchObject({ view: "home", activeCategoryId: null });
  });

  it("sends the stamp the app last saw with the retirement, so a stale click is refused", async () => {
    const id = aCategoryId();
    await openCategory(twoRows(id, 31));
    server.answers(`DELETE /api/categories/${id}`, { categories: [], unreadable: [], shadowed: [], library_dir: "a" });

    await store.dispatch(retireWorkbook({ categoryId: id }));

    expect(server.requestsFor(`DELETE /api/categories/${id}`)[0]?.query).toBe("?expected_mtime=31");
  });

  it("refuses to retire a category that is not open, before anything reaches the server", async () => {
    const id = aCategoryId();

    await store.dispatch(retireWorkbook({ categoryId: id }));

    expect(server.requests).toEqual([]);
    expect(toastTones()).toEqual(["error: That category is no longer open."]);
  });

  it("keeps the category on screen, repainted, when the retirement is refused", async () => {
    const id = aCategoryId();
    await openCategory(twoRows(id, 1));
    server.refuses(`DELETE /api/categories/${id}`, 409, STALE);
    server.answers(`GET /api/categories/${id}`, twoRows(id, 2, "what the owner typed in Excel"));

    await store.dispatch(retireWorkbook({ categoryId: id }));

    expect(store.getState().category.detail?.id).toBe(id);
    expect(noteOf(2)).toBe("what the owner typed in Excel");
    expect(store.getState().ui.view).not.toBe("home");
  });
});
