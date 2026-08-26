import "@fontsource-variable/space-grotesk";
import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import "../../src/index.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { Provider } from "react-redux";

import { App } from "../../src/App";
import { aTestStore } from "../../tests/support/aTestStore";
import { SURFACES, type SurfaceName } from "../surfaces";
import { ARRANGEMENTS } from "./arrangements";
import { serveProbeBackend } from "./aFakeBackend";

const SURFACE_PARAM = "surface";
const READY = "ready";

function requestedSurface(): SurfaceName {
  const asked = new URLSearchParams(window.location.search).get(SURFACE_PARAM);
  const spec = SURFACES.find((candidate) => candidate.name === asked);
  if (spec === undefined) throw new Error(`No layout probe surface is called "${asked}".`);
  return spec.name;
}

const container = document.getElementById("root");
if (container === null) throw new Error("The probe page is missing its #root element.");

const arrangement = ARRANGEMENTS[requestedSurface()];
serveProbeBackend(arrangement.turn, arrangement.library);
const store = aTestStore();

createRoot(container).render(
  <StrictMode>
    <Provider store={store}>
      <App />
    </Provider>
  </StrictMode>,
);

await arrangement.drive(store);
// The guard measures nothing until the surface it asked for is actually on screen.
document.body.dataset["probe"] = READY;
