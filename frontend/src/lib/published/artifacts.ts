/**
 * The artifacts a page reads from a pinned view, by name and by type, and
 * which of them each tab reads.
 *
 * One reader for each tab, so that a tab asks for exactly its own files when
 * it is first opened (AR-07). The contents are still in the site's existing
 * format, hence the existing types; step 3 of the rewrite replaces these with
 * generated ones.
 */

import type {
  CarPerformanceResult,
  ChartSeries,
  CornerAnalysisResult,
  Driver,
  IdealLapsResult,
  Lap,
  PacePredictionResult,
  PitStop,
  PositionReplayFrame,
  RaceControlMessage,
  RacePaceResult,
  Result,
  SessionSummary,
  Stint,
  StrategyResult,
  TeammateComparisonResult,
  TrackDominanceResult,
  TyreDegradationResult,
  WeatherSample
} from "../../types/domain";
import type { TelemetryIndex } from "../static-api-core.ts";
import type { SessionView } from "./client.ts";
import { PublishedDataError } from "./errors.ts";
import type { SessionTabId } from "./tabs.ts";

/** One file of a generation: where it is, and how it is read as what it is. */
export type ArtifactFile<T> = {
  readonly path: string;
  read(view: SessionView): Promise<T>;
};

/**
 * Every file a session page reads, except the telemetry laps, which are named
 * by the telemetry index and read two at a time (telemetry.ts).
 *
 * An object artifact names the fields a component maps over. Only that much
 * of a shape is checked, because a component that maps over a missing list
 * takes its tab down with a script error; what each row holds is vouched for
 * by the manifest's format version (rule 7).
 */
export const ARTIFACTS = {
  summary: recordOf<SessionSummary>("summary.json"),
  drivers: listOf<Driver>("drivers.json"),
  laps: listOf<Lap>("laps.json"),
  results: listOf<Result>("results.json"),
  stints: listOf<Stint>("stints.json"),
  pitStops: listOf<PitStop>("pit-stops.json"),
  weather: listOf<WeatherSample>("weather.json"),
  raceControl: listOf<RaceControlMessage>("race-control.json"),
  positionReplay: listOf<PositionReplayFrame>("position-replay.json"),
  lapTimes: listOf<ChartSeries>("analysis/lap-times.json"),
  racePace: recordOf<RacePaceResult>("analysis/race-pace.json", ["drivers"]),
  tyreDegradation: recordOf<TyreDegradationResult>("analysis/tyre-degradation.json", ["rows"]),
  idealLaps: recordOf<IdealLapsResult>("analysis/ideal-laps.json", ["rows"]),
  teammateComparison: recordOf<TeammateComparisonResult>("analysis/team-mate-comparison.json", ["rows"]),
  strategy: recordOf<StrategyResult>("analysis/strategy.json"),
  trackDominance: recordOf<TrackDominanceResult>("analysis/track-dominance.json", ["minisectors"]),
  cornerAnalysis: recordOf<CornerAnalysisResult>("analysis/corner-analysis.json", ["corners"]),
  carPerformance: recordOf<CarPerformanceResult>("analysis/car-performance.json", ["drivers"]),
  pacePrediction: recordOf<PacePredictionResult>("analysis/pace-prediction.json", ["drivers"]),
  telemetryIndex: recordOf<TelemetryIndex>("telemetry/index.json", ["laps"])
} as const;

type TabFiles = {
  /** Without any one of these the tab has nothing to show. */
  readonly required: ReadonlyArray<ArtifactFile<unknown>>;
  /** A generation may leave these out; the tab says so where each would be. */
  readonly optional: ReadonlyArray<ArtifactFile<unknown>>;
};

const A = ARTIFACTS;

/**
 * What each tab reads when it is opened. The optional ones are the analyses
 * the old dashboard already treated as optional. With a manifest the page
 * knows which a generation holds before it asks, so a missing one costs no
 * request and is not an error.
 *
 * The telemetry tab also reads two telemetry laps for each comparison, which
 * no table can list.
 */
const TAB_FILES: Readonly<Record<SessionTabId, TabFiles>> = {
  overview: { required: [A.summary, A.drivers, A.laps, A.racePace, A.stints, A.pitStops], optional: [] },
  "lap-times": { required: [A.lapTimes, A.drivers], optional: [] },
  "race-pace": { required: [A.racePace, A.tyreDegradation, A.laps, A.drivers], optional: [] },
  performance: {
    required: [A.drivers],
    optional: [A.idealLaps, A.teammateComparison, A.trackDominance, A.cornerAnalysis, A.carPerformance, A.pacePrediction]
  },
  strategy: { required: [A.stints, A.pitStops], optional: [A.strategy] },
  telemetry: { required: [A.telemetryIndex, A.laps, A.drivers], optional: [] },
  "position-replay": { required: [A.positionReplay, A.drivers], optional: [] },
  weather: { required: [A.weather], optional: [] },
  "race-control": { required: [A.raceControl], optional: [] },
  results: { required: [A.results, A.drivers], optional: [] }
};

export type TabArtifacts = { readonly required: string[]; readonly optional: string[] };

/** The paths a tab reads when it is opened. */
export function tabArtifacts(tab: SessionTabId): TabArtifacts {
  const files = TAB_FILES[tab];
  return { required: files.required.map((file) => file.path), optional: files.optional.map((file) => file.path) };
}

export type TabAvailability = {
  /** Whether the generation holds everything the tab cannot do without. */
  readonly available: boolean;
  /** Required paths the generation does not hold. */
  readonly missing: string[];
  /** Optional paths the generation does not hold. */
  readonly absent: string[];
};

/** What a generation has of a tab's files. Makes no request: the manifest already says. */
export function tabAvailability(view: Pick<SessionView, "has">, tab: SessionTabId): TabAvailability {
  const { required, optional } = tabArtifacts(tab);
  const missing = required.filter((path) => !view.has(path));
  return { available: missing.length === 0, missing, absent: optional.filter((path) => !view.has(path)) };
}

export type SessionOverview = {
  readonly summary: SessionSummary;
  readonly drivers: Driver[];
  readonly laps: Lap[];
  readonly racePace: RacePaceResult;
  readonly stints: Stint[];
  readonly pitStops: PitStop[];
};

export async function readOverview(view: SessionView): Promise<SessionOverview> {
  requireListed(view, "overview");
  const [summary, drivers, laps, racePace, stints, pitStops] = await Promise.all([
    A.summary.read(view),
    A.drivers.read(view),
    A.laps.read(view),
    A.racePace.read(view),
    A.stints.read(view),
    A.pitStops.read(view)
  ]);
  return { summary, drivers, laps, racePace, stints, pitStops };
}

export type SessionLapTimes = {
  readonly series: ChartSeries[];
  readonly drivers: Driver[];
};

/**
 * One lap-time series for each driver, with the drivers the chart styles them
 * from: team-mates share a colour, and the driver list is what tells the two
 * lines apart (lib/driver-style.ts).
 */
export async function readLapTimes(view: SessionView): Promise<SessionLapTimes> {
  requireListed(view, "lap-times");
  const [series, drivers] = await Promise.all([A.lapTimes.read(view), A.drivers.read(view)]);
  return { series, drivers };
}

export type SessionRacePace = {
  readonly racePace: RacePaceResult;
  readonly tyreDegradation: TyreDegradationResult;
  readonly laps: Lap[];
  readonly drivers: Driver[];
};

export async function readRacePace(view: SessionView): Promise<SessionRacePace> {
  requireListed(view, "race-pace");
  const [racePace, tyreDegradation, laps, drivers] = await Promise.all([
    A.racePace.read(view),
    A.tyreDegradation.read(view),
    A.laps.read(view),
    A.drivers.read(view)
  ]);
  return { racePace, tyreDegradation, laps, drivers };
}

/** Each analysis is null when the generation does not hold it. */
export type SessionPerformance = {
  readonly drivers: Driver[];
  readonly idealLaps: IdealLapsResult | null;
  readonly teammateComparison: TeammateComparisonResult | null;
  readonly trackDominance: TrackDominanceResult | null;
  readonly cornerAnalysis: CornerAnalysisResult | null;
  readonly carPerformance: CarPerformanceResult | null;
  readonly pacePrediction: PacePredictionResult | null;
};

export async function readPerformance(view: SessionView): Promise<SessionPerformance> {
  requireListed(view, "performance");
  const [drivers, idealLaps, teammateComparison, trackDominance, cornerAnalysis, carPerformance, pacePrediction] =
    await Promise.all([
      A.drivers.read(view),
      readIfListed(view, A.idealLaps),
      readIfListed(view, A.teammateComparison),
      readIfListed(view, A.trackDominance),
      readIfListed(view, A.cornerAnalysis),
      readIfListed(view, A.carPerformance),
      readIfListed(view, A.pacePrediction)
    ]);
  return { drivers, idealLaps, teammateComparison, trackDominance, cornerAnalysis, carPerformance, pacePrediction };
}

/** `strategy` is null when the generation does not hold the analysis. */
export type SessionStrategy = {
  readonly stints: Stint[];
  readonly pitStops: PitStop[];
  readonly strategy: StrategyResult | null;
};

export async function readStrategy(view: SessionView): Promise<SessionStrategy> {
  requireListed(view, "strategy");
  const [stints, pitStops, strategy] = await Promise.all([
    A.stints.read(view),
    A.pitStops.read(view),
    readIfListed(view, A.strategy)
  ]);
  return { stints, pitStops, strategy };
}

export type SessionReplay = {
  readonly frames: PositionReplayFrame[];
  readonly drivers: Driver[];
};

/** The largest artifact of a session after the telemetry, at 2 to 4 MB. Read by its own tab only. */
export async function readPositionReplay(view: SessionView): Promise<SessionReplay> {
  requireListed(view, "position-replay");
  const [frames, drivers] = await Promise.all([A.positionReplay.read(view), A.drivers.read(view)]);
  return { frames, drivers };
}

export function readWeather(view: SessionView): Promise<WeatherSample[]> {
  return A.weather.read(view);
}

export function readRaceControl(view: SessionView): Promise<RaceControlMessage[]> {
  return A.raceControl.read(view);
}

export type SessionResults = {
  readonly results: Result[];
  readonly drivers: Driver[];
};

/** The classification, with the drivers it needs for names, teams and colours. */
export async function readResults(view: SessionView): Promise<SessionResults> {
  requireListed(view, "results");
  const [results, drivers] = await Promise.all([A.results.read(view), A.drivers.read(view)]);
  return { results, drivers };
}

/**
 * Fail before anything is requested when the generation lacks a file the tab
 * cannot do without. Reading them all at once would otherwise fetch the rest
 * of a tab that is about to say it has nothing to show.
 */
export function requireListed(view: SessionView, tab: SessionTabId): void {
  for (const file of TAB_FILES[tab].required) {
    if (!view.has(file.path)) {
      throw new PublishedDataError(
        "not_in_manifest",
        `${file.path} is not one of the files of this session's published generation.`,
        { session_key: view.pointer.session_key, generation: view.pointer.generation, path: file.path }
      );
    }
  }
}

/** Read a file the generation may leave out: null, and no request, when it did. */
export function readIfListed<T>(view: SessionView, file: ArtifactFile<T>): Promise<T | null> {
  return view.has(file.path) ? file.read(view) : Promise.resolve(null);
}

function listOf<T>(path: string): ArtifactFile<T[]> {
  return {
    path,
    async read(view) {
      const payload = await view.read<unknown>(path);
      if (!Array.isArray(payload)) {
        throw new PublishedDataError("invalid_artifact", `${path} is not a list.`, { path });
      }
      const rows: unknown[] = payload;
      return rows as T[];
    }
  };
}

function recordOf<T>(path: string, lists: ReadonlyArray<string> = []): ArtifactFile<T> {
  return {
    path,
    async read(view) {
      const payload = await view.read<unknown>(path);
      if (!isRecord(payload)) {
        throw new PublishedDataError("invalid_artifact", `${path} is not an object.`, { path });
      }
      for (const field of lists) {
        if (!Array.isArray(payload[field])) {
          throw new PublishedDataError("invalid_artifact", `${path} has no list of ${field}.`, { path, field });
        }
      }
      return payload as T;
    }
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
