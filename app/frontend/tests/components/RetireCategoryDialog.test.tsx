import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState, type ReactElement } from "react";
import { Provider } from "react-redux";
import { beforeEach, describe, expect, it } from "vitest";

import { RetireCategoryDialog } from "../../src/components/RetireCategoryDialog";
import { loadCategory } from "../../src/stores/categorySlice";
import { selectCategory } from "../../src/stores/uiSlice";
import type { CategoryDetail } from "../../src/types/CategoryDetail";
import { aCategoryDetail } from "../support/aCategoryDetail";
import { aFakeServer, type FakeServer } from "../support/aFakeServer";
import { aTestStore, type TestStore } from "../support/aTestStore";

const CLOSED = "The dialog is closed.";
const RETIRE = "Retire category";
const CONFIRMED_NAME = "A Watchlist";
const EMPTY_LIBRARY = { categories: [], unreadable: [], shadowed: [], library_dir: "a-library" };

/** Each test retires a workbook of its own: the write queue is module state that outlives one test. */
let categories = 0;

function aCategoryId(): string {
  categories += 1;
  return `retirable-${categories}`;
}

let server: FakeServer;
let store: TestStore;

function RetireStage({ detail }: { readonly detail: CategoryDetail }): ReactElement {
  const [open, setOpen] = useState(true);
  return open ? <RetireCategoryDialog detail={detail} onClose={() => setOpen(false)} /> : <p>{CLOSED}</p>;
}

async function openDialog(detail: CategoryDetail): Promise<void> {
  server.answers(`GET /api/categories/${detail.id}`, detail);
  store.dispatch(selectCategory(detail.id));
  await store.dispatch(loadCategory(detail.id));
  render(
    <Provider store={store}>
      <RetireStage detail={detail} />
    </Provider>,
  );
}

function dialog(): ReturnType<typeof within> {
  return within(screen.getByRole("dialog"));
}

function retireButton(): HTMLElement {
  return dialog().getByRole("button", { name: RETIRE });
}

function aRetirableCategory(): CategoryDetail {
  const id = aCategoryId();
  return aCategoryDetail({ id, name: CONFIRMED_NAME, rows: [{ row: 2, cells: { title: "One entry" } }] });
}

beforeEach(() => {
  server = aFakeServer();
  store = aTestStore();
});

describe("RetireCategoryDialog", () => {
  it("keeps the retiring button asleep until the name has been typed out in full", async () => {
    const user = userEvent.setup();
    const detail = aRetirableCategory();
    await openDialog(detail);

    expect(retireButton()).toBeDisabled();

    await user.type(dialog().getByRole("textbox"), CONFIRMED_NAME.slice(0, 4));
    expect(retireButton()).toBeDisabled();

    await user.type(dialog().getByRole("textbox"), CONFIRMED_NAME.slice(4));
    expect(retireButton()).toBeEnabled();
  });

  it("keeps the retiring button asleep for a name that is not this category's", async () => {
    const user = userEvent.setup();
    await openDialog(aRetirableCategory());

    await user.type(dialog().getByRole("textbox"), "Another Watchlist");

    expect(retireButton()).toBeDisabled();
  });

  it("accepts the name as it was typed, whatever the case and spacing", async () => {
    const user = userEvent.setup();
    await openDialog(aRetirableCategory());

    await user.type(dialog().getByRole("textbox"), `  ${CONFIRMED_NAME.toLowerCase()}  `);

    expect(retireButton()).toBeEnabled();
  });

  it("says where the workbook goes and that nothing is deleted", async () => {
    const detail = aRetirableCategory();
    await openDialog(detail);

    const hint = dialog().getByText(/leave the library/);

    expect(hint).toHaveTextContent(detail.file_name);
    expect(hint).toHaveTextContent("app/.backups");
    expect(hint).toHaveTextContent("Nothing is deleted");
  });

  it("warns that Windows will not move a file Excel is holding", async () => {
    const detail = aCategoryDetail({ id: aCategoryId(), name: CONFIRMED_NAME, lockedByExcel: true });
    await openDialog(detail);

    expect(dialog().getByText(/open in Excel/)).toBeInTheDocument();
  });

  it("sends the retirement with the stamp the app last saw once the name is confirmed", async () => {
    const user = userEvent.setup();
    const detail = aRetirableCategory();
    server.answers(`DELETE /api/categories/${detail.id}`, EMPTY_LIBRARY);
    await openDialog(detail);

    await user.type(dialog().getByRole("textbox"), CONFIRMED_NAME);
    await user.click(retireButton());

    await waitFor(() => {
      expect(server.requestsFor(`DELETE /api/categories/${detail.id}`)).toHaveLength(1);
    });
    expect(store.getState().category.detail).toBeNull();
    expect(store.getState().ui.view).toBe("home");
  });

  it("leaves the category open and the button ready to try again when the retirement is refused", async () => {
    const user = userEvent.setup();
    const detail = aRetirableCategory();
    server.refuses(`DELETE /api/categories/${detail.id}`, 423, {
      error: "WorkbookLockedError",
      message: "That workbook is open in Excel.",
    });
    await openDialog(detail);

    await user.type(dialog().getByRole("textbox"), CONFIRMED_NAME);
    await user.click(retireButton());

    await waitFor(() => {
      expect(retireButton()).toBeEnabled();
    });
    expect(store.getState().category.detail?.id).toBe(detail.id);
    expect(store.getState().ui.toasts.map((toast) => toast.message)).toEqual(["That workbook is open in Excel."]);
  });

  it("retires nothing when the dialog is cancelled", async () => {
    const user = userEvent.setup();
    const detail = aRetirableCategory();
    await openDialog(detail);
    const asked = server.requests.length;

    await user.type(dialog().getByRole("textbox"), CONFIRMED_NAME);
    await user.click(dialog().getByRole("button", { name: "Cancel" }));

    expect(screen.getByText(CLOSED)).toBeInTheDocument();
    expect(server.requests).toHaveLength(asked);
  });

  it("retires nothing when the dialog is dismissed with Escape", async () => {
    const user = userEvent.setup();
    const detail = aRetirableCategory();
    await openDialog(detail);
    const asked = server.requests.length;

    await user.type(dialog().getByRole("textbox"), CONFIRMED_NAME);
    await user.keyboard("{Escape}");

    expect(screen.getByText(CLOSED)).toBeInTheDocument();
    expect(server.requests).toHaveLength(asked);
  });

  it("names the category in its title without that standing in for the typed confirmation", async () => {
    const detail = aRetirableCategory();
    await openDialog(detail);

    expect(dialog().getByText("Retire this category", { selector: ".dialog__title" })).toBeInTheDocument();
    expect(retireButton()).toBeDisabled();
  });
});
