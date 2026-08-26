const DEFAULT_PORT = 5286;

/** Its own port, so a guard run never fights the app you have open on 5284. */
export const PROBE_PORT = Number(process.env.TV_LAYOUT_PORT ?? DEFAULT_PORT);

export const PROBE_ORIGIN = `http://127.0.0.1:${PROBE_PORT}`;
