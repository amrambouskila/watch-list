import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

// Vitest does not unmount between tests the way Jest does, so without this a component test leaks
// its DOM into the next one and queries match elements from a test that already finished.
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
