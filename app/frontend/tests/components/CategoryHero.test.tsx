import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CategoryHero } from "../../src/components/CategoryHero";
import type { AccentPalette } from "../../src/utils/accentPalette";

const PALETTE: AccentPalette = { accent: "#7ee2a8", dim: "#1f2937", soft: "#7ee2a824" };
const ALT = "Artwork on the card";

function show(imageUrl: string | null | undefined, seed = "a-category"): HTMLElement {
  const { container } = render(<CategoryHero seed={seed} palette={PALETTE} imageUrl={imageUrl} alt={ALT} />);
  return container;
}

function backdropIn(container: HTMLElement): Element | null {
  return container.querySelector(".hero__art");
}

describe("CategoryHero", () => {
  it.each([
    ["a PNG drop-in", "/heroes/a-category.png"],
    ["an SVG drop-in", "/heroes/a-category.svg"],
    ["a cache-busted PNG, whose query must not be read as part of the extension", "/heroes/a-category.png?v=1712"],
    ["a cache-busted SVG", "/heroes/a-category.svg?v=1712"],
    ["an extension the backend wrote in capitals", "/heroes/a-category.PNG"],
    ["a fragment after the extension", "/heroes/a-category.png#mark"],
  ])("lays %s over the generated backdrop as a logo", (_case, url) => {
    const container = show(url);

    expect(screen.getByAltText(ALT)).toHaveClass("hero__logo");
    expect(backdropIn(container)).not.toBeNull();
  });

  it.each([
    ["a JPEG", "/heroes/a-category.jpg"],
    ["a cache-busted JPEG", "/heroes/a-category.jpg?v=1712"],
    ["a WebP", "/heroes/a-category.webp"],
    ["a file whose query mentions another format", "/heroes/a-category.jpg?fallback=a-category.png"],
  ])("lets %s fill the card in place of the backdrop", (_case, url) => {
    const container = show(url);

    expect(screen.getByAltText(ALT)).toHaveClass("hero__image");
    expect(backdropIn(container)).toBeNull();
  });

  it.each([
    ["no artwork has been chosen", null],
    ["the listing carries no artwork field at all", undefined],
    ["the artwork field is empty", ""],
  ])("shows the generated backdrop alone when %s", (_case, url) => {
    const container = show(url);

    expect(screen.queryByAltText(ALT)).toBeNull();
    expect(backdropIn(container)).not.toBeNull();
  });

  it("draws the same backdrop for a category every time, so a card stays recognisable", () => {
    const first = show(null, "the-same-category").querySelector(".hero__art g");
    const second = show(null, "the-same-category").querySelector(".hero__art g");

    expect(first?.getAttribute("transform")).toBe(second?.getAttribute("transform"));
  });

  it("draws different backdrops for different categories", () => {
    const first = show(null, "one-category").querySelector(".hero__art g");
    const second = show(null, "another-category").querySelector(".hero__art g");

    expect(first?.getAttribute("transform")).not.toBe(second?.getAttribute("transform"));
  });
});
