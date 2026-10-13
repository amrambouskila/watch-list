import { createReadStream, readdirSync } from "node:fs";
import { extname, join } from "node:path";
import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

import { PROBE_PORT } from "./probeServer";

const FRONTEND_ROOT = fileURLToPath(new URL("..", import.meta.url));
const APP_PUBLIC = fileURLToPath(new URL("../public", import.meta.url));
const PROBE_PUBLIC = fileURLToPath(new URL("probes/public", import.meta.url));

const MEDIA_TYPE_BY_SUFFIX: Readonly<Record<string, string>> = {
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".webp": "image/webp",
  ".gif": "image/gif",
  ".ico": "image/x-icon",
};
const OPAQUE_MEDIA_TYPE = "application/octet-stream";
const QUERY = "?";
const INTERNAL_ERROR = 500;

/**
 * Serve the app's own `public/` beside the probes' fixtures.
 *
 * The probes mount the real components, and one of them names an asset by absolute URL: the TMDB
 * mark the attribution has to show unmodified. The probe root has a `public/` of its own, so that
 * URL would answer 404 here and the guard would measure a box production never draws. Copying the
 * file into the fixtures instead would leave two of an asset whose whole point is being byte for
 * byte what its owner published, so the real directory is served rather than duplicated.
 *
 * The map is built from that directory once, and only the names in it are ever answered, so no
 * request can reach past it. Anything the probes' own `public/` already provides is left out of the
 * map rather than shadowed, so a fixture always beats the app's file of the same name.
 *
 * It has to be registered before Vite's own middlewares rather than after them, because that stack
 * is terminal: measured here, an `<img>` for a name Vite does not know is answered `200 text/html`
 * by the SPA fallback and a `fetch` for it is answered 404, so a middleware installed behind them
 * never sees the request at all. Excluding the fixtures above is what keeps that safe — every name
 * left in the map is one Vite has no meaning for.
 */
function theAppsPublicFiles(): Plugin {
  const fixtures = new Set(
    readdirSync(PROBE_PUBLIC, { withFileTypes: true })
      .filter((entry) => entry.isFile())
      .map((entry) => entry.name),
  );
  const files = new Map<string, string>(
    readdirSync(APP_PUBLIC, { withFileTypes: true })
      .filter((entry) => entry.isFile() && !fixtures.has(entry.name))
      .map((entry) => [`/${entry.name}`, join(APP_PUBLIC, entry.name)]),
  );

  return {
    name: "the-apps-public-files",
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        const file = files.get((request.url ?? "").split(QUERY)[0] ?? "");
        if (file === undefined) {
          next();
          return;
        }
        response.setHeader("Content-Type", MEDIA_TYPE_BY_SUFFIX[extname(file)] ?? OPAQUE_MEDIA_TYPE);
        const bytes = createReadStream(file);
        // A file read that fails after the directory was listed answers 500, rather than throwing on
        // the stream and taking the whole probe server down mid-run.
        bytes.on("error", () => {
          if (!response.headersSent) response.statusCode = INTERNAL_ERROR;
          response.end();
        });
        bytes.pipe(response);
      });
    },
  };
}

export default defineConfig({
  root: fileURLToPath(new URL("probes", import.meta.url)),
  plugins: [react(), theAppsPublicFiles()],
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
