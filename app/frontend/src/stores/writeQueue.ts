interface Stamped {
  readonly mtime: number;
}

const chains = new Map<string, Promise<unknown>>();
const latest = new Map<string, number>();

/** Record the newest mtime seen for a workbook, from a load or a write response. */
export function noteMtime(categoryId: string, mtime: number): void {
  latest.set(categoryId, mtime);
}

/**
 * Serialise writes to one workbook, threading each response's mtime into the next request.
 *
 * Every write carries the mtime the client last saw, and the server refuses one whose mtime is
 * stale so an edit made in Excel is never overwritten. Two quick clicks would otherwise both
 * send the mtime rendered on screen, and the second would be rejected as a conflict it caused
 * itself. The queue cannot read the fresh mtime back out of Redux either — a thunk's promise
 * settles before the store commits its result — so it tracks the mtime here instead.
 */
export function enqueueWrite<T extends Stamped>(
  categoryId: string,
  seed: number,
  run: (mtime: number) => Promise<T>,
): Promise<T> {
  const start = (): Promise<T> => run(latest.get(categoryId) ?? seed);
  const tail = chains.get(categoryId) ?? Promise.resolve();
  const next = tail.then(start, start).then((result) => {
    noteMtime(categoryId, result.mtime);
    return result;
  });
  chains.set(
    categoryId,
    next.then(
      () => undefined,
      () => undefined,
    ),
  );
  return next;
}
