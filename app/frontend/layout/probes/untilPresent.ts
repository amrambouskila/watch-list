const POLL_INTERVAL_MS = 16;
const DEADLINE_MS = 10_000;

/**
 * Wait for the app to paint something the probe then acts on, the way a person waits for it.
 *
 * `saying` picks one of several matches by its words, because the app carries no test hooks and a
 * person finds the Add entry button by reading it, not by its class.
 */
export async function untilPresent<T extends Element>(selector: string, saying?: string): Promise<T> {
  const deadline = performance.now() + DEADLINE_MS;
  for (;;) {
    const found = [...document.querySelectorAll<T>(selector)].find(
      (candidate) => saying === undefined || (candidate.textContent ?? "").trim() === saying,
    );
    if (found !== undefined) return found;
    if (performance.now() > deadline) {
      const wanted = saying === undefined ? selector : `${selector} saying "${saying}"`;
      throw new Error(`Nothing matched ${wanted} in ${DEADLINE_MS}ms.`);
    }
    await new Promise<void>((resolve) => window.setTimeout(resolve, POLL_INTERVAL_MS));
  }
}
