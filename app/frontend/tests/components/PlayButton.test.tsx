import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Provider } from "react-redux";
import { expect, it } from "vitest";

import { PlayButton } from "../../src/components/PlayButton";
import { aCuratedEntryRead } from "../support/aCuratedEntryRead";
import { aTestStore } from "../support/aTestStore";

it("opens by entry identity, never trusting a title-level library ID as a stream file", async () => {
  const store = aTestStore();
  const entry = { ...aCuratedEntryRead(), availability: "in_library" as const, jellyfin_item_id: "a-series-not-a-file" };
  render(<Provider store={store}><PlayButton mtime={1} entry={entry} title="A Show" /></Provider>);
  await userEvent.click(screen.getByRole("button", { name: "Play A Show" }));
  expect(store.getState().ui.playing).toEqual({ entryId: entry.id, title: "A Show", categoryId: entry.category_slug, mtime: 1 });
});
