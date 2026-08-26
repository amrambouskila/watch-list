import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState, type ReactElement } from "react";
import { describe, expect, it } from "vitest";

import { HeroCandidates } from "../../src/components/HeroCandidates";
import type { HeroCandidate } from "../../src/types/HeroCandidate";
import { aHeroCandidate } from "../support/aHeroCandidate";

const NOTHING_PICKED = "nothing picked yet";

interface StageProps {
  readonly candidates: readonly HeroCandidate[];
  readonly disabled?: boolean;
}

/** The pick is only meaningful as the position the backend is handed, so the stage renders it. */
function CandidateStage({ candidates, disabled = false }: StageProps): ReactElement {
  const [picked, setPicked] = useState(NOTHING_PICKED);
  return (
    <>
      <HeroCandidates candidates={candidates} disabled={disabled} onPick={(choice) => setPicked(String(choice))} />
      <p>picked: {picked}</p>
    </>
  );
}

function picks(): HTMLElement[] {
  return screen.getAllByRole("button", { name: "Use this one" });
}

describe("HeroCandidates", () => {
  it("offers one pick for each image on the table", () => {
    render(<CandidateStage candidates={[aHeroCandidate(), aHeroCandidate(), aHeroCandidate()]} />);

    expect(picks()).toHaveLength(3);
  });

  it("hands back the position of the image that was picked", async () => {
    const user = userEvent.setup();
    render(<CandidateStage candidates={[aHeroCandidate(), aHeroCandidate(), aHeroCandidate()]} />);

    await user.click(picks()[2] as HTMLElement);

    expect(screen.getByText("picked: 2")).toBeInTheDocument();
  });

  it("refuses a pick while artwork is already being saved", async () => {
    const user = userEvent.setup();
    render(<CandidateStage candidates={[aHeroCandidate(), aHeroCandidate()]} disabled />);

    expect(picks()[0]).toBeDisabled();
    await user.click(picks()[0] as HTMLElement);

    expect(screen.getByText(`picked: ${NOTHING_PICKED}`)).toBeInTheDocument();
  });

  it("shows the image only when the model gave a real address for it", () => {
    render(
      <CandidateStage
        candidates={[
          aHeroCandidate({ url: "https://example.org/artwork.jpg", description: "a real one" }),
          aHeroCandidate({ url: "I could not find an image", description: "an unshowable one" }),
        ]}
      />,
    );

    expect(screen.getByAltText("a real one")).toHaveAttribute("src", "https://example.org/artwork.jpg");
    expect(screen.queryByAltText("an unshowable one")).toBeNull();
    expect(screen.getByText("I could not find an image")).toBeInTheDocument();
  });

  it("links to the page an image came from, and names the file when there is no page to link to", () => {
    render(
      <CandidateStage
        candidates={[
          aHeroCandidate({ page: "https://example.org/the-page", source_file: "Linked.jpg" }),
          aHeroCandidate({ page: "no source page", source_file: "Unlinked.jpg" }),
        ]}
      />,
    );

    expect(screen.getByRole("link", { name: "Linked.jpg" })).toHaveAttribute("href", "https://example.org/the-page");
    expect(screen.queryByRole("link", { name: "Unlinked.jpg" })).toBeNull();
    expect(screen.getByText("Unlinked.jpg")).toBeInTheDocument();
  });

  it("shows the licence beside each image, since that is what makes it usable", () => {
    render(<CandidateStage candidates={[aHeroCandidate({ licence: "CC0 1.0" })]} />);

    const offered = within(screen.getByRole("list", { name: "Proposed artwork" }));
    expect(offered.getByText("CC0 1.0")).toBeInTheDocument();
  });

  it("opens a source page away from the app, without handing it the app's referrer", () => {
    render(<CandidateStage candidates={[aHeroCandidate({ page: "https://example.org/the-page" })]} />);

    const link = screen.getByRole("link");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noreferrer noopener");
  });
});
