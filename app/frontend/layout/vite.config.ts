import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

import { PROBE_PORT } from "./probeServer";

const FRONTEND_ROOT = fileURLToPath(new URL("..", import.meta.url));

export default defineConfig({
  root: fileURLToPath(new URL("probes", import.meta.url)),
  plugins: [react()],
  // Beside the app's own cache rather than under the probe root, which has no node_modules.
  cacheDir: fileURLToPath(new URL("../node_modules/.vite-layout", import.meta.url)),
  server: {
    // Vite's default host resolves to ::1 on Windows, which the guard's 127.0.0.1 never reaches.
    host: "127.0.0.1",
    port: PROBE_PORT,
    strictPort: true,
    // The probes mount the app itself, so the server has to reach src/ and node_modules above them.
    fs: { allow: [FRONTEND_ROOT] },
  },
});
