/**
 * The artifacts a page reads from a pinned view, by name and by type, and
 * which of them each tab reads.
 *
 * One reader for each tab, so that a tab asks for exactly its own files when
 * it is first opened (AR-07).
 *
 * A file's type is not written here. It is looked up from its path in
 * `GenerationFiles`, which is the published schema, so a path the format
 * does not have, or a file read as something the schema does not say it is,
 * does not compile.
 */

import type { PositionReplayFrame } from "../../types/domain";
import type { SessionView } from "./client.ts";
import { PublishedDataError } from "./errors.ts";
import type { SessionTabId } from "./tabs.ts";
import type {
  CarPerformance,
  CornerAnalysis,
  Driver,
  GenerationFiles,
  IdealLaps,
  Lap,
  LapTimeSeries,
  PacePrediction,
  PitStop,
  RaceControlMessage,
  RacePace,
  Result,
  SessionSummary,
  Stint,
  Strategy,
  TeammateComparison,
  TrackDominance,
  TyreDegradation,
  WeatherSample
} from "./types.ts";

/** One file of a generation: where it is, and how it is read as what it is. */
export type ArtifactFile<T> = {
  readonly path: string;
  read(view: SessionView): Promise<T>;
};

/**
 * Every file a session page reads, except the drivers' telemetry, which the
 * telemetry index names and which is read a driver at a time (telemetry.ts).
 *
 * An object artifact names the fields a component maps over. Only that much
 * of a shape is checked, because a component that maps over a missing list
 * takes its tab down with a script error; what each row holds is vouched for
 * by the manifest's format version (rule 7).
 */
export const ARTIFACTS = {
  summary: recordOf("summary.json"),
  drivers: listOf("drivers.json"),
  results: listOf("results.json"),
  laps: listOf("laps.json"),
  stints: listOf("stints.json"),
  pitStops: listOf("pit-stops.json"),
  weather: listOf("weather.json"),
  raceControl: listOf("race-control.json"),
  strategy: recordOf("analysis/strategy.json", ["undercut_overcut", "caveats"]),
  lapTimes: listOf("analysis/lap-times.json"),
  racePace: recordOf("analysis/race-pace.json", ["drivers", "stints", "caveats"]),
  tyreDegradation: recordOf("analysis/tyre-degradation.json", ["rows", "caveats"]),
  idealLaps: recordOf("analysis/ideal-laps.json", ["rows"]),
  teammateComparison: recordOf("analysis/team-mate-comparison.json", ["rows", "caveats"]),
  trackDominance: recordOf("analysis/track-dominance.json", ["minisectors", "excluded_drivers", "caveats"]),
  cornerAnalysis: recordOf("analysis/corner-analysis.json", ["corners", "caveats"]),
  carPerformance: recordOf("analysis/car-performance.json", ["drivers", "caveats"]),
  pacePrediction: recordOf("analysis/pace-prediction.json", ["drivers", "caveats"]),
  telemetryIndex: recordOf("telemetry/index.json", ["channels", "drivers"]),
  // Still read on its format-1 shape; it moves to its schema type with the
  // page that shows it.
  positionReplay: formerListOf<PositionReplayFrame>("position-replay.json")
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
 * The telemetry tab also reads the telemetry of the drivers it compares,
 * which no table can list: the index says which files there are.
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
  telemetry: { required: [A.telemetryIndex, A.drivers], optional: [] },
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
  readonly drivers: ReadonlyArray<Driver>;
  readonly laps: ReadonlyArray<Lap>;
  readonly racePace: RacePace;
  readonly stints: ReadonlyArray<Stint>;
  readonly pitStops: ReadonlyArray<PitStop>;
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
  readonly series: ReadonlyArray<LapTimeSeries>;
  readonly drivers: ReadonlyArray<Driver>;
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
  readonly racePace: RacePace;
  readonly tyreDegradation: TyreDegradation;
  readonly laps: ReadonlyArray<Lap>;
  readonly drivers: ReadonlyArray<Driver>;
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
  /** The session's code, from its pointer: which analyses a session has depends on what kind it is. */
  readonly sessionType: string;
  readonly drivers: ReadonlyArray<Driver>;
  readonly idealLaps: IdealLaps | null;
  readonly teammateComparison: TeammateComparison | null;
  readonly trackDominance: TrackDominance | null;
  readonly cornerAnalysis: CornerAnalysis | null;
  readonly carPerformance: CarPerformance | null;
  /** Published for a practice session only. */
  readonly pacePrediction: PacePrediction | null;
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
  return {
    sessionType: view.pointer.identity.session_type,
    drivers,
    idealLaps,
    teammateComparison,
    trackDominance,
    cornerAnalysis,
    carPerformance,
    pacePrediction
  };
}

/** `strategy` is null when the generation does not hold the analysis. */
export type SessionStrategy = {
  readonly stints: ReadonlyArray<Stint>;
  readonly pitStops: ReadonlyArray<PitStop>;
  readonly strategy: Strategy | null;
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
  readonly drivers: ReadonlyArray<Driver>;
};

/** The largest artifact of a session after the telemetry, at 2 to 4 MB. Read by its own tab only. */
export async function readPositionReplay(view: SessionView): Promise<SessionReplay> {
  requireListed(view, "position-replay");
  const [frames, drivers] = await Promise.all([A.positionReplay.read(view), A.drivers.read(view)]);
  return { frames, drivers };
}

export function readWeather(view: SessionView): Promise<ReadonlyArray<WeatherSample>> {
  return A.weather.read(view);
}

export function readRaceControl(view: SessionView): Promise<ReadonlyArray<RaceControlMessage>> {
  return A.raceControl.read(view);
}

export type SessionResults = {
  readonly results: ReadonlyArray<Result>;
  readonly drivers: ReadonlyArray<Driver>;
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

/** The files the schema says are lists, and the ones it says are objects. */
type ListPath = {
  [Path in keyof GenerationFiles]: GenerationFiles[Path] extends ReadonlyArray<unknown> ? Path : never;
}[keyof GenerationFiles];
type RecordPath = Exclude<keyof GenerationFiles, ListPath>;

/** The fields of an object that the schema says are lists. */
type ListField<T> = { [Field in keyof T]: T[Field] extends ReadonlyArray<unknown> ? Field : never }[keyof T] & string;

/** A file that is a list, read as the list the schema says it is. */
export function listOf<Path extends ListPath>(path: Path): ArtifactFile<GenerationFiles[Path]> {
  return { path, read: (view) => readList(view, path) };
}

/**
 * A file that is an object. `lists` names the fields a page maps over, which
 * are checked to be lists; they can only be fields the schema types as one.
 */
export function recordOf<Path extends RecordPath>(
  path: Path,
  lists: ReadonlyArray<ListField<GenerationFiles[Path]>> = []
): ArtifactFile<GenerationFiles[Path]> {
  return { path, read: (view) => readRecord(view, path, lists) };
}

/**
 * Read a path of a generation as the object the schema says is there. `path`
 * is the real path and `As` the schema's path for it; they differ only for a
 * driver's telemetry, which has one schema path for every driver's file.
 */
export function readRecord<As extends RecordPath>(
  view: SessionView,
  path: string,
  lists: ReadonlyArray<ListField<GenerationFiles[As]>> = []
): Promise<GenerationFiles[As]> {
  return checkedRecord<GenerationFiles[As]>(view, path, lists);
}

async function readList<T>(view: SessionView, path: string): Promise<T> {
  // The view takes the type on trust (client.ts); that it is a list at all
  // is what is checked here.
  const payload = await view.read<T>(path);
  if (!Array.isArray(payload)) {
    throw new PublishedDataError("invalid_artifact", `${path} is not a list.`, { path });
  }
  return payload;
}

async function checkedRecord<T>(view: SessionView, path: string, lists: ReadonlyArray<string>): Promise<T> {
  const payload = await view.read<T>(path);
  if (!isRecord(payload)) {
    throw new PublishedDataError("invalid_artifact", `${path} is not an object.`, { path });
  }
  for (const field of lists) {
    if (!Array.isArray(payload[field])) {
      throw new PublishedDataError("invalid_artifact", `${path} has no list of ${field}.`, { path, field });
    }
  }
  return payload;
}

function formerListOf<T>(path: string): ArtifactFile<T[]> {
  return { path, read: (view) => readList<T[]>(view, path) };
}


function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
