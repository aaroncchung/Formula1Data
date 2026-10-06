/**
 * One read of each artifact for a page, however many tabs ask for it.
 *
 * Seven of the ten tabs need the driver list and three need the laps. Each
 * tab asks for what it needs without knowing what the others hold (AR-07),
 * and this is where those requests meet.
 */

import type { SessionView } from "./client.ts";

const TELEMETRY_LAP = /^telemetry\/.+-lap-\d+\.json$/;

/**
 * The same view, which reads each artifact once.
 *
 * The first read of a path is shared by every later one, so the 400 kB of
 * laps is fetched and parsed once for a page. A read that fails is forgotten,
 * so that trying again asks again.
 *
 * What a read returns is therefore shared between tabs and must not be
 * changed by any of them.
 *
 * `share` leaves out what is read once and is large in number: the telemetry
 * laps, of which a race has over a thousand and a page compares two.
 */
export function shareReads(view: SessionView, share: (path: string) => boolean = isSharedArtifact): SessionView {
  const reads = new Map<string, Promise<unknown>>();
  const shared: SessionView = {
    pointer: view.pointer,
    manifest: view.manifest,
    has: (path) => view.has(path),
    read<T>(path: string): Promise<T> {
      if (!share(path)) {
        return view.read<T>(path);
      }
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

function isSharedArtifact(path: string): boolean {
  return !TELEMETRY_LAP.test(path);
}
