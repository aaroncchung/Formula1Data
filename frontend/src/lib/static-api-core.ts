import type { ApiErrorPayload, ApiResult } from "@/types/api";
import type {
  ChartSeries,
  Driver,
  EmptyStateResponse,
  Lap,
  LiveDisabledResponse,
  Meeting,
  PitStop,
  PositionReplayFrame,
  QualifyingDeltaResult,
  RaceControlMessage,
  RacePaceResult,
  Result,
  Season,
  Session,
  SessionSummary,
  Stint,
  TelemetryComparison,
  TelemetrySample,
  TyreDegradationResult,
  WeatherSample
} from "@/types/domain";

export const STATIC_DATA_SOURCE = "/data";

export type CatalogArtifact = {
  schema_version: number;
  generated_at: string;
  seasons: Season[];
  meetings: Meeting[];
  sessions: Session[];
  totals: Record<string, number>;
};

type SeasonArtifact = {
  schema_version: number;
  generated_at: string;
  season: Season;
  meetings: Meeting[];
  sessions: Session[];
};

export type TelemetryIndex = {
  schema_version: number;
  generated_at: string;
  session_id: string;
  max_samples_per_lap: number;
  laps: Array<{
    driver_code: string;
    lap_number: number;
    path: string;
    sample_count: number;
    raw_sample_count: number;
    size_bytes: number;
  }>;
};

export type ArtifactReader = <T>(path: string) => Promise<T>;

export class ApiClientError extends Error {
  constructor(
    message: string,
    public readonly payload: ApiErrorPayload,
    public readonly apiBaseUrl: string
  ) {
    super(message);
  }
}

export function createStaticApi(readArtifact: ArtifactReader) {
  const api = {
    catalog: () => readArtifact<CatalogArtifact>("catalog.json"),
    seasons: async () => (await api.catalog()).seasons,
    primarySession: async () => primarySession(await api.catalog()),
    meetings: async (year: number) => (await readSeason(year)).meetings,
    sessions: async (year: number, round: number) =>
      (await readSeason(year)).sessions.filter((session) => session.round === round),
    summary: (sessionId: string) => readSessionArtifact<SessionSummary>(sessionId, "summary.json"),
    drivers: (sessionId: string) => readSessionArtifact<Driver[]>(sessionId, "drivers.json"),
    laps: (sessionId: string) => readSessionArtifact<Lap[]>(sessionId, "laps.json"),
    results: (sessionId: string) => readSessionArtifact<Result[]>(sessionId, "results.json"),
    stints: (sessionId: string) => readSessionArtifact<Stint[]>(sessionId, "stints.json"),
    pitStops: (sessionId: string) => readSessionArtifact<PitStop[]>(sessionId, "pit-stops.json"),
    weather: (sessionId: string) => readSessionArtifact<WeatherSample[]>(sessionId, "weather.json"),
    raceControl: (sessionId: string) =>
      readSessionArtifact<RaceControlMessage[]>(sessionId, "race-control.json"),
    lapTimes: (sessionId: string) =>
      readSessionArtifact<ChartSeries[]>(sessionId, "analysis/lap-times.json"),
    racePace: (sessionId: string) =>
      readSessionArtifact<RacePaceResult>(sessionId, "analysis/race-pace.json"),
    tyreDegradation: (sessionId: string) =>
      readSessionArtifact<TyreDegradationResult>(sessionId, "analysis/tyre-degradation.json"),
    qualifyingDelta: (sessionId: string, driverA: string, driverB: string) =>
      qualifyingDelta(sessionId, driverA, driverB),
    idealLaps: (sessionId: string) =>
      readSessionArtifact<Record<string, unknown>>(sessionId, "analysis/ideal-laps.json"),
    teammateComparison: (sessionId: string) =>
      readSessionArtifact<Record<string, unknown>>(sessionId, "analysis/team-mate-comparison.json"),
    strategy: (sessionId: string) =>
      readSessionArtifact<Record<string, unknown>>(sessionId, "analysis/strategy.json"),
    telemetryIndex: (sessionId: string) => readTelemetryIndex(sessionId),
    telemetryLap: (sessionId: string, driver: string, lap: number) =>
      readTelemetryLap(sessionId, driver, lap),
    telemetryCompare: (sessionId: string, driverA: string, lapA: number, driverB: string, lapB: number) =>
      telemetryCompare(sessionId, driverA, lapA, driverB, lapB),
    positionReplay: async (sessionId: string) => {
      const frames = await readSessionArtifact<PositionReplayFrame[]>(sessionId, "position-replay.json");
      if (!frames.length) {
        return emptyState(
          "Position/location data is unavailable for this session.",
          "Generate telemetry artifacts with position samples."
        );
      }
      return frames;
    },
    liveCurrentSession: async () => liveDisabled(),
    liveTiming: async () => liveDisabled(),
    liveRaceControl: async () => liveDisabled(),
    livePositions: async () => liveDisabled(),
    liveWeather: async () => liveDisabled()
  };

  async function readSeason(year: number): Promise<SeasonArtifact> {
    return readArtifact<SeasonArtifact>(`seasons/${year}.json`);
  }

  async function readSessionArtifact<T>(sessionId: string, filePath: string): Promise<T> {
    return readArtifact<T>(`sessions/${sessionId}/${filePath}`);
  }

  async function readTelemetryIndex(sessionId: string): Promise<TelemetryIndex | null> {
    try {
      return await readSessionArtifact<TelemetryIndex>(sessionId, "telemetry/index.json");
    } catch (error) {
      if (isArtifactNotFound(error)) {
        return null;
      }
      throw error;
    }
  }

  async function readTelemetryLap(
    sessionId: string,
    driver: string,
    lap: number
  ): Promise<TelemetrySample[]> {
    const index = await readTelemetryIndex(sessionId);
    const entry = index?.laps.find(
      (item) => item.driver_code === driver.toUpperCase() && item.lap_number === lap
    );
    if (!entry) {
      return [];
    }
    return readSessionArtifact<TelemetrySample[]>(sessionId, entry.path);
  }

  async function telemetryCompare(
    sessionId: string,
    driverA: string,
    lapA: number,
    driverB: string,
    lapB: number
  ): Promise<TelemetryComparison | EmptyStateResponse> {
    const index = await readTelemetryIndex(sessionId);
    if (!index || !index.laps.length) {
      return telemetryUnavailableState();
    }

    const [samplesA, samplesB, laps, drivers] = await Promise.all([
      readTelemetryLapFromIndex(index, sessionId, driverA, lapA),
      readTelemetryLapFromIndex(index, sessionId, driverB, lapB),
      api.laps(sessionId),
      api.drivers(sessionId)
    ]);

    if (!samplesA.length || !samplesB.length) {
      return emptyState(
        "Telemetry is unavailable for one or both selected laps.",
        "Generate telemetry artifacts for the selected driver and lap."
      );
    }

    const step = Math.max(1, Math.ceil(samplesA.length / 300));
    const alignedA = samplesA.filter((_, index) => index % step === 0);
    const alignedB = alignedA.map((sample) => nearestByDistance(samplesB, sample.distance_m));
    const speedA = values(alignedA, "speed_kph");
    const speedB = values(alignedB, "speed_kph");

    return {
      session_id: sessionId,
      driver_a: driverMeta(driverA, lapA, laps, drivers),
      driver_b: driverMeta(driverB, lapB, laps, drivers),
      distance_m: alignedA.map((sample) => Number(sample.distance_m || 0)),
      speed_a: speedA,
      speed_b: speedB,
      throttle_a: values(alignedA, "throttle_pct"),
      throttle_b: values(alignedB, "throttle_pct"),
      brake_a: values(alignedA, "brake").map(boolToInt),
      brake_b: values(alignedB, "brake").map(boolToInt),
      rpm_a: values(alignedA, "rpm"),
      rpm_b: values(alignedB, "rpm"),
      gear_a: values(alignedA, "gear"),
      gear_b: values(alignedB, "gear"),
      drs_a: values(alignedA, "drs"),
      drs_b: values(alignedB, "drs"),
      delta_speed_kph: speedA.map((speed, index) => {
        const other = speedB[index];
        return speed !== null && other !== null ? Math.round((speed - other) * 100) / 100 : null;
      }),
      caveats: ["Telemetry is aligned by nearest distance sample and downsampled for UI performance."]
    };
  }

  async function readTelemetryLapFromIndex(
    index: TelemetryIndex,
    sessionId: string,
    driver: string,
    lap: number
  ): Promise<TelemetrySample[]> {
    const entry = index.laps.find(
      (item) => item.driver_code === driver.toUpperCase() && item.lap_number === lap
    );
    if (!entry) {
      return [];
    }
    return readSessionArtifact<TelemetrySample[]>(sessionId, entry.path);
  }

  async function qualifyingDelta(
    sessionId: string,
    driverA: string,
    driverB: string
  ): Promise<QualifyingDeltaResult> {
    const [laps, drivers] = await Promise.all([api.laps(sessionId), api.drivers(sessionId)]);
    const fastestA = fastestLap(laps, driverA);
    const fastestB = fastestLap(laps, driverB);
    if (!fastestA || !fastestB) {
      return {
        session_id: sessionId,
        driver_a: driverA.toUpperCase(),
        driver_b: driverB.toUpperCase(),
        sector_delta_ms: {},
        telemetry: null,
        caveats: ["A fastest lap could not be found for one or both drivers."]
      };
    }

    const telemetry = await telemetryCompare(
      sessionId,
      driverA,
      fastestA.lap_number,
      driverB,
      fastestB.lap_number
    );
    const caveats = isEmptyState(telemetry)
      ? ["Telemetry is missing for at least one selected fastest lap."]
      : [];

    return {
      session_id: sessionId,
      driver_a: driverA.toUpperCase(),
      driver_b: driverB.toUpperCase(),
      sector_delta_ms: {
        sector_1: delta(fastestA, fastestB, "sector_1_ms"),
        sector_2: delta(fastestA, fastestB, "sector_2_ms"),
        sector_3: delta(fastestA, fastestB, "sector_3_ms"),
        lap: delta(fastestA, fastestB, "lap_time_ms")
      },
      telemetry: isEmptyState(telemetry) ? null : telemetry,
      caveats
    };
  }

  return api;
}

function primarySession(catalog: CatalogArtifact): Session {
  const available = catalog.sessions.filter((session) => session.status !== "missing");
  const sessions = available.length ? available : catalog.sessions;
  const selected = [...sessions].sort((left, right) => {
    const leftRank = sessionSortRank(left);
    const rightRank = sessionSortRank(right);
    return leftRank - rightRank;
  }).at(-1);
  if (!selected) {
    throw new ApiClientError(
      "No session artifacts are available",
      {
        code: "artifact_not_found",
        message: "No session artifacts are available",
        details: { path: "catalog.json" }
      },
      STATIC_DATA_SOURCE
    );
  }

  return selected;
}

function sessionSortRank(session: Session): number {
  const sessionOrder: Record<string, number> = { FP1: 1, FP2: 2, FP3: 3, SQ: 4, S: 5, Q: 6, R: 7 };
  return session.year * 10000 + session.round * 10 + (sessionOrder[session.type.toUpperCase()] || 0);
}

export async function safeApi<T>(loader: () => Promise<T>): Promise<ApiResult<T>> {
  try {
    return { ok: true, data: await loader() };
  } catch (error) {
    if (error instanceof ApiClientError) {
      return { ok: false, error: error.payload, apiBaseUrl: error.apiBaseUrl };
    }
    return {
      ok: false,
      apiBaseUrl: STATIC_DATA_SOURCE,
      error: { code: "unknown", message: error instanceof Error ? error.message : "Unknown error" }
    };
  }
}

export type ApiFailure = Extract<ApiResult<unknown>, { ok: false }>;

export function isApiFailure(result: { ok: boolean }): result is ApiFailure {
  return !result.ok;
}

export function isEmptyState(value: unknown): value is EmptyStateResponse {
  return Boolean(value && typeof value === "object" && "reason" in value);
}

export function isLiveDisabled(value: unknown): value is LiveDisabledResponse {
  return Boolean(value && typeof value === "object" && "enabled" in value && value.enabled === false);
}

export function isArtifactNotFound(error: unknown): error is ApiClientError {
  return error instanceof ApiClientError && error.payload.code === "artifact_not_found";
}

export function artifactError(path: string, source: string, cause?: unknown): ApiClientError {
  const missing = isMissingFileError(cause);
  const payload = {
    code: missing ? "artifact_not_found" : "artifact_unavailable",
    message: missing ? "Static artifact was not generated" : "Static artifact could not be loaded",
    details: { path, source }
  };
  return new ApiClientError(payload.message, payload, source);
}

function emptyState(reason: string, action: string): EmptyStateResponse {
  return { reason, action, details: {} };
}

function telemetryUnavailableState(): EmptyStateResponse {
  return emptyState(
    "No telemetry lap artifacts are available for this session.",
    "Generate telemetry artifacts to enable driver and lap comparisons."
  );
}

function liveDisabled(): LiveDisabledResponse {
  return {
    enabled: false,
    reason: "Live mode is not part of the static historical deployment.",
    setup: [
      "Historical browsing reads committed JSON artifacts from /data.",
      "Add a separate serverless live adapter later if OpenF1 live timing is needed."
    ]
  };
}

function nearestByDistance(rows: TelemetrySample[], distance: number): TelemetrySample {
  return rows.reduce((nearest, row) =>
    Math.abs(Number(row.distance_m || 0) - distance) <
    Math.abs(Number(nearest.distance_m || 0) - distance)
      ? row
      : nearest
  );
}

function values(rows: TelemetrySample[], field: keyof TelemetrySample): Array<number | null> {
  return rows.map((row) => {
    const value = row[field];
    return typeof value === "number" || typeof value === "boolean" ? Number(value) : null;
  });
}

function boolToInt(value: number | null): number | null {
  if (value === null) {
    return null;
  }
  return value ? 1 : 0;
}

function driverMeta(driverCode: string, lapNumber: number, laps: Lap[], drivers: Driver[]) {
  const code = driverCode.toUpperCase();
  const lap = laps.find((item) => item.driver_code === code && item.lap_number === lapNumber);
  const driver = drivers.find((item) => item.code === code);
  return {
    driver_code: code,
    team: driver?.team.name || null,
    lap_time_ms: lap?.lap_time_ms || null,
    compound: lap?.compound || null,
    session: lap?.session_id || null,
    lap_number: lapNumber
  };
}

function fastestLap(laps: Lap[], driverCode: string): Lap | null {
  const code = driverCode.toUpperCase();
  const driverLaps = laps.filter(
    (lap) => lap.driver_code === code && lap.lap_time_ms != null && !lap.is_deleted
  );
  if (!driverLaps.length) {
    return null;
  }
  return driverLaps.reduce((fastest, lap) =>
    Number(lap.lap_time_ms) < Number(fastest.lap_time_ms) ? lap : fastest
  );
}

function delta(lapA: Lap, lapB: Lap, field: "sector_1_ms" | "sector_2_ms" | "sector_3_ms" | "lap_time_ms") {
  if (lapA[field] === null || lapB[field] === null) {
    return null;
  }
  return Number(lapB[field]) - Number(lapA[field]);
}

function isMissingFileError(cause: unknown): boolean {
  return Boolean(
    cause &&
      typeof cause === "object" &&
      "code" in cause &&
      (cause as { code?: string }).code === "ENOENT"
  );
}
