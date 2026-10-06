/**
 * Telemetry comparison over a pinned session view.
 *
 * The comparison itself is the one the site already has, in
 * `createStaticApi` (lib/static-api-core.ts): it reads the telemetry index,
 * the two laps, the lap list and the drivers, and lines the two laps up by
 * distance. This only changes where those files come from: the generation the
 * view pinned, so the two laps and the lap times beside them are from one
 * publication (rule 1).
 */

import type { EmptyStateResponse, TelemetryComparison } from "../types/domain";
import type { SessionView } from "./published/client.ts";
import { ApiClientError, createStaticApi } from "./static-api-core.ts";

export type TelemetryComparer = (
  driverA: string,
  lapA: number,
  driverB: string,
  lapB: number
) => Promise<TelemetryComparison | EmptyStateResponse>;

export function telemetryComparerOf(view: SessionView): TelemetryComparer {
  // The static API names a session by an id in every path. Under a view the
  // session is already fixed, so the id is only a label to take off again.
  const sessionId = String(view.pointer.session_key);
  const prefix = `sessions/${sessionId}/`;

  const api = createStaticApi(<T>(path: string): Promise<T> => {
    const file = path.startsWith(prefix) ? path.slice(prefix.length) : path;
    if (!view.has(file)) {
      // What the static API expects for a file that was never generated. It
      // turns this into "no telemetry for this session" where the file is
      // optional, which is the right thing to show for a generation without it.
      return Promise.reject(
        new ApiClientError(
          "Static artifact was not generated",
          {
            code: "artifact_not_found",
            message: `${file} is not one of the files of this session's published generation.`,
            details: { path: file }
          },
          "published data"
        )
      );
    }
    return view.read<T>(file);
  });

  return (driverA, lapA, driverB, lapB) => api.telemetryCompare(sessionId, driverA, lapA, driverB, lapB);
}
