import { render, screen } from "@testing-library/react";
import { Provider } from "react-redux";
import { describe, expect, it } from "vitest";

import { AvailabilityBadge } from "../../src/components/AvailabilityBadge";
import { PlayButton } from "../../src/components/PlayButton";
import type { Availability } from "../../src/types/Availability";
import { aCuratedEntryRead } from "../support/aCuratedEntryRead";
import { aTestStore } from "../support/aTestStore";

describe("AvailabilityBadge", () => {
  it.each<[Availability, string]>([
    ["in_library", "In library"],
    ["not_in_library", "Opens on your subscription"],
    ["ambiguous", "Needs a pick"],
  ])("labels %s with text and an icon, and gates Play", (availability, label) => {
    const entry = { ...aCuratedEntryRead(), availability };
    const { container } = render(
      <Provider store={aTestStore()}>
        <AvailabilityBadge availability={availability} />
        <PlayButton mtime={1} entry={entry} title="A Show" />
      </Provider>,
    );
    expect(screen.getByText(label)).toBeInTheDocument();
    expect(container.querySelector(".availability svg[aria-hidden='true']")).not.toBeNull();
    expect(screen.queryByRole("button", { name: "Play A Show" }) !== null).toBe(availability === "in_library");
  });
});
