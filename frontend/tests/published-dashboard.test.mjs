import assert from "node:assert/strict";
import test from "node:test";

import {
  readLapTimes,
  readOverview,
  readPerformance,
  readPositionReplay,
  readRaceControl,
  readRacePace,
  readResults,
  readStrategy,
  readWeather,
  tabArtifacts,
  tabAvailability
} from "../src/lib/published/artifacts.ts";
import { notifyWhenGone } from "../src/lib/published/session.ts";
import { shareReads } from "../src/lib/published/share.ts";
import { DEFAULT_SESSION_TAB, SESSION_TABS, hashOfTab, tabFromHash } from "../src/lib/published/tabs.ts";
import { compareTelemetry, defaultComparison, readTelemetry } from "../src/lib/published/telemetry.ts";

import {
  bucketOf,
  clientOf,
  failureOf,
  generationPrefix,
  removeGeneration,
  republish,
  SESSION_KEY
} from "./support/published-bucket.mjs";

// ---------------------------------------------------------------------------
// A whole session
// ---------------------------------------------------------------------------

function lap(driver, number, time, overrides = {}) {
  return {
    session_id: "2026-08-r",
    driver_code: driver,
    lap_number: number,
    lap_time_ms: time,
    compound: "MEDIUM",
    tyre_age: number,
    stint: 1,
    is_pit_in_lap: false,
    is_pit_out_lap: false,
    is_deleted: false,
    is_accurate: number > 1,
    track_status: "1",
    ...overrides
  };
}

/** One lap of telemetry: five samples along 4 km, `pace` ms for each kilometre. */
function telemetryLap(driver, number, pace) {
  return [0, 1000, 2000, 3000, 4000].map((distance, index) => ({
    session_id: "2026-08-r",
    driver_code: driver,
    lap_number: number,
    distance_m: distance,
    speed_kph: 200 + index * 20,
    throttle_pct: 100,
    brake: false,
    rpm: 11000,
    gear: 7,
    drs: 0,
    x: distance,
    y: index,
    relative_time_ms: index * pace
  }));
}

const LAPS = [
  lap("RUS", 1, 80_000),
  lap("RUS", 2, 70_500),
  lap("RUS", 3, 70_100),
  lap("VER", 1, 80_500),
  lap("VER", 2, 70_300),
  lap("VER", 3, 70_900)
];

const TELEMETRY_LAPS = LAPS.map((row) => ({
  driver_code: row.driver_code,
  lap_number: row.lap_number,
  path: `telemetry/${row.driver_code.toLowerCase()}-lap-${row.lap_number}.json`,
  sample_count: 5,
  raw_sample_count: 5,
  size_bytes: 1024
}));

/**
 * Every file a session page reads, in the smallest form each tab accepts,
 * added to the fixture's generation (which has the drivers, the results and
 * the summary). The telemetry laps are files of their own.
 */
const SESSION_FILES = {
  "laps.json": LAPS,
  "stints.json": [{ session_id: "2026-08-r", driver_code: "RUS", stint: 1, compound: "MEDIUM", start_lap: 1, end_lap: 3, lap_count: 3 }],
  "pit-stops.json": [{ session_id: "2026-08-r", driver_code: "RUS", lap_number: 3, duration_ms: 21552, local_time: "0 days 01:22:52.191000" }],
  "weather.json": [{ session_id: "2026-08-r", lap_number: null, timestamp: "0 days 00:00:38.376000", air_temp_c: 33.6, track_temp_c: 53.2, rainfall: false }],
  "race-control.json": [{ session_id: "2026-08-r", lap_number: 1, timestamp: "2026-06-28 12:20:00", category: "Flag", message: "GREEN LIGHT - PIT EXIT OPEN", flag: "GREEN" }],
  "position-replay.json": [{ session_id: "2026-08-r", frame_index: 0, lap_number: 1, timestamp_ms: 3_425_000, positions: [{ driver_code: "RUS", x: 1, y: 2 }] }],
  "analysis/lap-times.json": [{ name: "RUS", x: [1, 2, 3], y: [80_000, 70_500, 70_100], color: "#27F4D2", metadata: {} }],
  "analysis/race-pace.json": { session_id: "2026-08-r", drivers: [{ driver_code: "RUS", median_lap_ms: 70_300, lap_count: 2 }], stints: [], caveats: [] },
  "analysis/tyre-degradation.json": { session_id: "2026-08-r", rows: [], caveats: [] },
  "analysis/ideal-laps.json": { session_id: "2026-08-r", rows: [] },
  "analysis/team-mate-comparison.json": { session_id: "2026-08-r", rows: [], caveats: [] },
  "analysis/strategy.json": { session_id: "2026-08-r", stints: [], compound_usage: { MEDIUM: 1 }, pit_stops: [], undercut_overcut: [], race_control_overlays: [], caveats: [] },
  "analysis/track-dominance.json": { session_id: "2026-08-r", representative_laps: [], minisector_count: 0, minisectors: [], caveats: [] },
  "analysis/corner-analysis.json": { session_id: "2026-08-r", representative_laps: [], corners: [], caveats: [] },
  "analysis/car-performance.json": { session_id: "2026-08-r", drivers: [], teams: [], caveats: [] },
  "analysis/pace-prediction.json": { session_id: "2026-08-r", available: false, session_type: "Race", drivers: [], teams: [], caveats: [] },
  "telemetry/index.json": { schema_version: 1, generated_at: "2026-10-06T00:04:33Z", session_id: "2026-08-r", max_samples_per_lap: 300, laps: TELEMETRY_LAPS },
  ...Object.fromEntries(TELEMETRY_LAPS.map((entry) => [entry.path, telemetryLap(entry.driver_code, entry.lap_number, 17_000 + entry.lap_number * 100)]))
};

/**
 * A bucket holding one whole session, without the files named in `without`,
 * and a view on it with the request log cleared. `requested()` is what has
 * been asked of the generation since, as paths inside it.
 */
async function wholeSession({ without = [], share = false } = {}) {
  const bucket = bucketOf();
  const generation = republish(bucket, SESSION_FILES, { without });
  const opened = await clientOf(bucket).openSession(SESSION_KEY);
  const view = share ? shareReads(opened) : opened;
  bucket.requests.length = 0;
  const prefix = generationPrefix(generation);
  const requested = () =>
    bucket.keys().map((key) => {
      assert.ok(key.startsWith(prefix), `a request left the pinned generation: ${key}`);
      return key.slice(prefix.length);
    });
  return { bucket, view, generation, requested, forget: () => (bucket.requests.length = 0) };
}

// ---------------------------------------------------------------------------
// The tabs
// ---------------------------------------------------------------------------

test("a fragment names a tab the way the old dashboard's links did", () => {
  assert.equal(tabFromHash("#telemetry"), "telemetry");
  assert.equal(tabFromHash("#lap-times"), "lap-times");
  assert.equal(tabFromHash("#Position%20Replay"), "position-replay");
  assert.equal(tabFromHash("race-control"), "race-control");
  assert.equal(tabFromHash("#RESULTS"), "results");
  for (const tab of SESSION_TABS) {
    assert.equal(tabFromHash(hashOfTab(tab.id)), tab.id);
  }
});

test("a fragment that names no tab names none", () => {
  for (const hash of ["", "#", "#live", "#lap", "#%E0%A4%A", "#results/extra"]) {
    assert.equal(tabFromHash(hash), null, hash);
  }
  assert.equal(DEFAULT_SESSION_TAB, "overview");
});

test("every tab of the old dashboard is there, in its order", () => {
  assert.deepEqual(
    SESSION_TABS.map((tab) => tab.label),
    ["Overview", "Lap Times", "Race Pace", "Performance", "Strategy", "Telemetry", "Position Replay", "Weather", "Race Control", "Results"]
  );
});

// The table of which files each tab reads. A change here changes what a
// visitor downloads, so it is spelled out and not derived.
const TAB_READS = {
  overview: { required: ["summary.json", "drivers.json", "laps.json", "analysis/race-pace.json", "stints.json", "pit-stops.json"], optional: [] },
  "lap-times": { required: ["analysis/lap-times.json", "drivers.json"], optional: [] },
  "race-pace": { required: ["analysis/race-pace.json", "analysis/tyre-degradation.json", "laps.json", "drivers.json"], optional: [] },
  performance: {
    required: ["drivers.json"],
    optional: [
      "analysis/ideal-laps.json",
      "analysis/team-mate-comparison.json",
      "analysis/track-dominance.json",
      "analysis/corner-analysis.json",
      "analysis/car-performance.json",
      "analysis/pace-prediction.json"
    ]
  },
  strategy: { required: ["stints.json", "pit-stops.json"], optional: ["analysis/strategy.json"] },
  telemetry: { required: ["telemetry/index.json", "laps.json", "drivers.json"], optional: [] },
  "position-replay": { required: ["position-replay.json", "drivers.json"], optional: [] },
  weather: { required: ["weather.json"], optional: [] },
  "race-control": { required: ["race-control.json"], optional: [] },
  results: { required: ["results.json", "drivers.json"], optional: [] }
};

// The telemetry tab also reads the two laps it compares first.
const FIRST_COMPARISON = ["telemetry/rus-lap-3.json", "telemetry/ver-lap-2.json"];

const TAB_READERS = {
  overview: readOverview,
  "lap-times": readLapTimes,
  "race-pace": readRacePace,
  performance: readPerformance,
  strategy: readStrategy,
  telemetry: readTelemetry,
  "position-replay": readPositionReplay,
  weather: readWeather,
  "race-control": readRaceControl,
  results: readResults
};

test("the table of what each tab reads is the one written down", () => {
  assert.deepEqual(Object.keys(TAB_READS), SESSION_TABS.map((tab) => tab.id));
  for (const tab of SESSION_TABS) {
    assert.deepEqual(tabArtifacts(tab.id), TAB_READS[tab.id], tab.id);
  }
});

for (const tab of SESSION_TABS) {
  test(`opening the ${tab.id} tab requests its own artifacts and no others`, async () => {
    const { view, requested } = await wholeSession({ share: true });

    await TAB_READERS[tab.id](view);

    const expected = [...TAB_READS[tab.id].required, ...TAB_READS[tab.id].optional];
    if (tab.id === "telemetry") {
      expected.push(...FIRST_COMPARISON);
    }
    assert.deepEqual(requested().sort(), expected.sort());
  });
}

test("the position replay is requested by its own tab and by no other", async () => {
  for (const tab of SESSION_TABS.filter((item) => item.id !== "position-replay")) {
    const { view, requested } = await wholeSession({ share: true });

    await TAB_READERS[tab.id](view);

    assert.ok(!requested().includes("position-replay.json"), tab.id);
  }
});

test("a file two tabs need is requested once for the page", async () => {
  const { view, requested } = await wholeSession({ share: true });

  for (const tab of SESSION_TABS) {
    await TAB_READERS[tab.id](view);
  }

  const all = requested();
  assert.equal(all.length, new Set(all).size, `requested twice: ${all.filter((path, index) => all.indexOf(path) !== index)}`);
  // Seven tabs read the drivers and three read the laps.
  assert.equal(all.filter((path) => path === "drivers.json").length, 1);
  assert.equal(all.filter((path) => path === "laps.json").length, 1);
});

for (const tab of SESSION_TABS) {
  const [firstRequired] = TAB_READS[tab.id].required;
  test(`the ${tab.id} tab without ${firstRequired} says so before requesting anything`, async () => {
    const { view, requested } = await wholeSession({ without: [firstRequired] });

    const failure = await failureOf(TAB_READERS[tab.id](view));

    assert.equal(failure.code, "not_in_manifest");
    assert.equal(failure.details.path, firstRequired);
    assert.deepEqual(requested(), []);
    assert.deepEqual(tabAvailability(view, tab.id).missing, [firstRequired]);
    assert.equal(tabAvailability(view, tab.id).available, false);
  });
}

test("a required file that is missing costs the tabs that need it and no others", async () => {
  const { view } = await wholeSession({ without: ["laps.json"] });

  const available = SESSION_TABS.filter((tab) => tabAvailability(view, tab.id).available).map((tab) => tab.id);

  assert.deepEqual(available, ["lap-times", "performance", "strategy", "position-replay", "weather", "race-control", "results"]);
  assert.equal((await readResults(view)).results.length, 2);
  assert.equal((await readWeather(view)).length, 1);
});

// The analyses the old dashboard treated as optional. With a manifest the
// page knows they are absent before it asks.
test("an analysis the generation leaves out is absent without a request, and its tab still opens", async () => {
  const optional = TAB_READS.performance.optional;
  const { view, requested } = await wholeSession({ without: [...optional, "analysis/strategy.json"] });

  const performance = await readPerformance(view);
  assert.equal(performance.drivers.length, 2);
  assert.deepEqual(
    [performance.idealLaps, performance.teammateComparison, performance.trackDominance, performance.cornerAnalysis, performance.carPerformance, performance.pacePrediction],
    [null, null, null, null, null, null]
  );
  assert.deepEqual(requested(), ["drivers.json"]);

  const strategy = await readStrategy(view);
  assert.equal(strategy.strategy, null);
  assert.equal(strategy.pitStops.length, 1);
  assert.deepEqual(tabAvailability(view, "strategy"), { available: true, missing: [], absent: ["analysis/strategy.json"] });
  assert.deepEqual(tabAvailability(view, "performance").absent, optional);
});

test("one optional analysis can be absent while the others are read", async () => {
  const { view, requested } = await wholeSession({ without: ["analysis/corner-analysis.json"] });

  const performance = await readPerformance(view);

  assert.equal(performance.cornerAnalysis, null);
  assert.notEqual(performance.trackDominance, null);
  assert.notEqual(performance.pacePrediction, null);
  assert.ok(!requested().includes("analysis/corner-analysis.json"));
  assert.equal(requested().length, 6);
});

// AR-07: one artifact that failed to load used to replace the whole page.
test("an artifact that cannot be read fails its own tab and leaves the others", async () => {
  const { bucket, view, generation } = await wholeSession({ share: true });
  const weatherKey = `${generationPrefix(generation)}weather.json`;
  bucket.fault = (key) => (key === weatherKey ? new Response("Service Unavailable", { status: 503 }) : undefined);

  const failed = await failureOf(readWeather(view));
  assert.equal(failed.code, "unavailable");

  for (const tab of SESSION_TABS.filter((item) => item.id !== "weather")) {
    await TAB_READERS[tab.id](view);
  }

  // Trying again asks again, and gets it once the outage is over.
  bucket.fault = () => undefined;
  assert.equal((await readWeather(view)).length, 1);
  assert.equal(bucket.count(weatherKey), 2);
});

test("an artifact in the wrong shape is invalid, whichever shape it should have", async () => {
  const wrong = {
    "weather.json": { error: "no weather" },
    "summary.json": [],
    "analysis/race-pace.json": { session_id: "2026-08-r", caveats: [] },
    "analysis/tyre-degradation.json": { session_id: "2026-08-r", rows: "none" },
    "telemetry/index.json": { schema_version: 1 }
  };
  const bucket = bucketOf();
  republish(bucket, { ...SESSION_FILES, ...wrong });
  const view = await clientOf(bucket).openSession(SESSION_KEY);

  assert.equal((await failureOf(readWeather(view))).code, "invalid_artifact");
  assert.equal((await failureOf(readOverview(view))).code, "invalid_artifact");
  assert.equal((await failureOf(readRacePace(view))).code, "invalid_artifact");
  assert.equal((await failureOf(readTelemetry(view))).code, "invalid_artifact");
  assert.match((await failureOf(readTelemetry(view))).message, /telemetry\/index\.json has no list of laps/);
  // The tabs that do not read those files are untouched.
  assert.equal((await readResults(view)).results.length, 2);
  assert.equal((await readStrategy(view)).stints.length, 1);
});

// ---------------------------------------------------------------------------
// Sharing reads between tabs
// ---------------------------------------------------------------------------

test("a shared view reads each artifact once, also when two tabs ask at the same time", async () => {
  const { view, requested } = await wholeSession({ share: true });

  const [first, second] = await Promise.all([view.read("drivers.json"), view.read("drivers.json")]);
  const third = await view.read("drivers.json");

  assert.equal(first, second);
  assert.equal(first, third);
  assert.deepEqual(requested(), ["drivers.json"]);
});

test("a read that failed is not remembered", async () => {
  const { bucket, view, requested } = await wholeSession({ share: true });
  bucket.fault = () => new TypeError("fetch failed");

  assert.equal((await failureOf(view.read("laps.json"))).code, "unavailable");
  assert.equal((await failureOf(view.read("laps.json"))).code, "unavailable");
  bucket.fault = () => undefined;

  assert.equal((await view.read("laps.json")).length, LAPS.length);
  assert.deepEqual(requested(), ["laps.json", "laps.json", "laps.json"]);
});

// A race has over a thousand of them and a page compares two at a time.
test("telemetry laps are not kept by a shared view", async () => {
  const { view, requested } = await wholeSession({ share: true });

  await view.read("telemetry/rus-lap-3.json");
  await view.read("telemetry/rus-lap-3.json");
  await view.read("telemetry/index.json");
  await view.read("telemetry/index.json");

  assert.deepEqual(requested(), ["telemetry/rus-lap-3.json", "telemetry/rus-lap-3.json", "telemetry/index.json"]);
});

test("a shared view is still the pinned view: same pointer, same manifest, same refusals", async () => {
  const { view, requested } = await wholeSession();
  const shared = shareReads(view);

  assert.equal(shared.pointer, view.pointer);
  assert.equal(shared.manifest, view.manifest);
  assert.ok(Object.isFrozen(shared));
  assert.equal(shared.has("laps.json"), true);
  assert.equal(shared.has("nothing.json"), false);
  assert.equal((await failureOf(shared.read("nothing.json"))).code, "not_in_manifest");
  assert.deepEqual(requested(), []);
});

test("a shared view still tells its holder when its generation is gone", async () => {
  const { bucket, view, generation } = await wholeSession();
  let told = 0;
  const shared = shareReads(notifyWhenGone(view, () => (told += 1)));
  removeGeneration(bucket, generation);

  assert.equal((await failureOf(readOverview(shared))).code, "generation_gone");
  assert.equal(told, 1);
});

// ---------------------------------------------------------------------------
// Telemetry
// ---------------------------------------------------------------------------

test("the first comparison is the fastest lap of each of the two quickest drivers", () => {
  assert.deepEqual(defaultComparison(TELEMETRY_LAPS, LAPS), [
    { driver: "RUS", lap: 3 },
    { driver: "VER", lap: 2 }
  ]);
});

test("a lap without telemetry, and a deleted lap, cannot be the lap compared", () => {
  const withoutRussellsBest = TELEMETRY_LAPS.filter((entry) => !(entry.driver_code === "RUS" && entry.lap_number === 3));
  assert.deepEqual(defaultComparison(withoutRussellsBest, LAPS)[0], { driver: "VER", lap: 2 });
  assert.deepEqual(defaultComparison(withoutRussellsBest, LAPS)[1], { driver: "RUS", lap: 2 });

  const deleted = LAPS.map((row) => (row.driver_code === "VER" && row.lap_number === 2 ? { ...row, is_deleted: true } : row));
  assert.deepEqual(defaultComparison(TELEMETRY_LAPS, deleted)[1], { driver: "VER", lap: 3 });
});

// What the old dashboard always did: the first two entries of the index,
// which are lap 1 of the first two drivers.
test("without lap times the first comparison is the first lap of two different drivers", () => {
  const untimed = LAPS.map((row) => ({ ...row, lap_time_ms: null }));

  assert.deepEqual(defaultComparison(TELEMETRY_LAPS, untimed), [
    { driver: "RUS", lap: 1 },
    { driver: "VER", lap: 1 }
  ]);
  assert.deepEqual(defaultComparison(TELEMETRY_LAPS, []), [
    { driver: "RUS", lap: 1 },
    { driver: "VER", lap: 1 }
  ]);
});

test("one driver's laps are compared with each other, and one lap with nothing", () => {
  const russell = TELEMETRY_LAPS.filter((entry) => entry.driver_code === "RUS");

  assert.deepEqual(defaultComparison(russell, LAPS), [
    { driver: "RUS", lap: 1 },
    { driver: "RUS", lap: 2 }
  ]);
  assert.equal(defaultComparison(russell.slice(0, 1), LAPS), null);
  assert.equal(defaultComparison([], LAPS), null);
});

test("the telemetry tab opens on the index and the two laps it compares", async () => {
  const { view, requested } = await wholeSession({ share: true });

  const telemetry = await readTelemetry(view);

  assert.equal(telemetry.laps.length, 6);
  assert.deepEqual(telemetry.pair, [
    { driver: "RUS", lap: 3 },
    { driver: "VER", lap: 2 }
  ]);
  assert.equal(telemetry.notice, null);
  // The comparison is the old reader's, with the lap and driver it looks up.
  assert.deepEqual(telemetry.comparison.driver_a, {
    driver_code: "RUS",
    team: "Mercedes",
    lap_time_ms: 70_100,
    compound: "MEDIUM",
    session: "2026-08-r",
    lap_number: 3
  });
  assert.equal(telemetry.comparison.driver_b.team, "Red Bull Racing");
  assert.deepEqual(telemetry.comparison.distance_m, [0, 1000, 2000, 3000, 4000]);
  // Russell's lap 3 runs 17,300 ms a kilometre and Verstappen's lap 2 17,200.
  assert.deepEqual(telemetry.comparison.delta_time_ms, [0, -100, -200, -300, -400]);
  assert.deepEqual(requested().sort(), ["drivers.json", "laps.json", "telemetry/index.json", ...FIRST_COMPARISON].sort());
});

test("a later comparison requests the two laps it compares and nothing else", async () => {
  const { view, requested, forget } = await wholeSession({ share: true });
  await readTelemetry(view);
  forget();

  const comparison = await compareTelemetry(view, { driver: "VER", lap: 3 }, { driver: "RUS", lap: 2 });

  assert.equal(comparison.driver_a.driver_code, "VER");
  assert.equal(comparison.driver_a.lap_time_ms, 70_900);
  assert.equal(comparison.driver_b.lap_number, 2);
  assert.deepEqual(requested().sort(), ["telemetry/rus-lap-2.json", "telemetry/ver-lap-3.json"]);
});

test("a lap the index does not list compares to a notice, without the pipeline's advice", async () => {
  const { view, requested, forget } = await wholeSession({ share: true });
  await readTelemetry(view);
  forget();

  const result = await compareTelemetry(view, { driver: "RUS", lap: 99 }, { driver: "VER", lap: 2 });

  assert.deepEqual(result, { reason: "Telemetry is unavailable for one or both selected laps." });
  assert.deepEqual(requested(), ["telemetry/ver-lap-2.json"]);
});

test("a first comparison that cannot be loaded leaves the tab open, with the reason", async () => {
  const { bucket, view, generation } = await wholeSession({ share: true });
  const lapKey = `${generationPrefix(generation)}telemetry/rus-lap-3.json`;
  bucket.fault = (key) => (key === lapKey ? new Response("Service Unavailable", { status: 503 }) : undefined);

  const telemetry = await readTelemetry(view);

  assert.equal(telemetry.laps.length, 6);
  assert.equal(telemetry.comparison, null);
  assert.equal(telemetry.notice.reason, "The telemetry of RUS lap 3 and VER lap 2 could not be loaded.");
  assert.match(telemetry.notice.action, /rus-lap-3\.json answered 503/);
  // Every other lap is still there to compare.
  bucket.fault = () => undefined;
  assert.equal((await compareTelemetry(view, { driver: "RUS", lap: 2 }, { driver: "VER", lap: 2 })).driver_a.lap_number, 2);
});

test("an index that names a lap the generation does not hold says so in the tab", async () => {
  const { view } = await wholeSession({ share: true, without: ["telemetry/ver-lap-2.json"] });

  const telemetry = await readTelemetry(view);

  assert.equal(telemetry.comparison, null);
  assert.match(telemetry.notice.action, /telemetry\/ver-lap-2\.json is not part of this session's published data/);
});

test("a generation that goes while the telemetry tab opens is passed on, not shown as a notice", async () => {
  const { bucket, view, generation } = await wholeSession({ share: true });
  for (const key of [...bucket.stored.keys()]) {
    if (key.startsWith(`${generationPrefix(generation)}telemetry/`) && !key.endsWith("index.json")) {
      bucket.stored.delete(key);
    }
  }

  assert.equal((await failureOf(readTelemetry(view))).code, "generation_gone");
});

test("a session with no telemetry laps opens to a notice and requests no lap", async () => {
  const bucket = bucketOf();
  const generation = republish(bucket, { ...SESSION_FILES, "telemetry/index.json": { ...SESSION_FILES["telemetry/index.json"], laps: [] } });
  const view = shareReads(await clientOf(bucket).openSession(SESSION_KEY));
  bucket.requests.length = 0;

  const telemetry = await readTelemetry(view);

  assert.deepEqual(telemetry.laps, []);
  assert.equal(telemetry.pair, null);
  assert.equal(telemetry.comparison, null);
  assert.match(telemetry.notice.reason, /needs two laps with telemetry/);
  assert.ok(bucket.keys().every((key) => !/-lap-\d+\.json$/.test(key)));
  assert.ok(bucket.keys().every((key) => key.startsWith(generationPrefix(generation))));
});
