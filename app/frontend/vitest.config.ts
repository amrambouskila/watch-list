import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/**/*.test.{ts,tsx}"],
    coverage: {
      provider: "v8",
      reporter: ["text", "html"],
      include: ["src/**/*.{ts,tsx}"],
      // The Vite entry point mounts the real app against the real backend; there is nothing in it
      // to assert that rendering the tree under test does not already prove.
      exclude: ["src/main.tsx"],
    },
  },
});
