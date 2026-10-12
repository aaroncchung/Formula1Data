/**
 * One read of each artifact for a page, however many tabs ask for it.
 *
 * Seven of the ten tabs need the driver list and two need the laps. Each
 * tab asks for what it needs without knowing what the others hold (AR-07),
 * and this is where those requests meet.
 */

import type { SessionView } from "./client.ts";

/**
 * The same view, which reads each artifact once.
 *
 * The first read of a path is shared by every later one, so the 400 kB of
 * laps is fetched and parsed once for a page. A read that fails is forgotten,
 * so that trying again asks again.
 *
 * A driver's telemetry is kept like everything else. It is the largest file
 * a page reads, about a megabyte, and a reader comparing laps comes back to
 * the same driver again and again; keeping it makes each later comparison of
 * that driver free. A page holds as many of them as it has compared drivers,
 * and they go when the page does.
 *
 * What a read returns is therefore shared between tabs and must not be
 * changed by any of them, which is why the files are typed read-only.
 */
export function shareReads(view: SessionView): SessionView {
  const reads = new Map<string, Promise<unknown>>();
  const shared: SessionView = {
    pointer: view.pointer,
    manifest: view.manifest,
    has: (path) => view.has(path),
    read<T>(path: string): Promise<T> {
      const held = reads.get(path);
      if (held) {
        // The view takes `T` on trust for every read (client.ts); a second
        // reader of the same path is trusted the same way.
        return held as Promise<T>;
      }
      const read = view.read<T>(path);
      reads.set(path, read);
      read.catch(() => {
        if (reads.get(path) === read) {
          reads.delete(path);
        }
      });
      return read;
    }
  };
  return Object.freeze(shared);
}
