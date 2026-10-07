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
import { compareTelemetry, defaultComparison, readTelemetry, telemetryLaps } from "../src/lib/published/telemetry.ts";

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
    driver_code: driver,
    lap_number: number,
    lap_time_ms: time,
    sector_1_ms: null,
    sector_2_ms: null,
    sector_3_ms: null,
    compound: "MEDIUM",
    tyre_age: number,
    stint: 1,
    position: null,
    is_pit_in_lap: false,
    is_pit_out_lap: false,
    is_deleted: false,
    is_accurate: number > 1,
    track_status: "1",
    ...overrides
  };
}

/** One lap of telemetry: five samples along 4 km, `pace` ms for each kilometre. */
function telemetryLap(number, pace) {
  const samples = [0, 1, 2, 3, 4];
  return {
    lap_number: number,
    start_ms: 3_500_000 + number * 80_000,
    time_ms: samples.map((index) => index * pace),
    distance_m: samples.map((index) => index * 1000),
    speed_kph: samples.map((index) => 200 + index * 20),
    throttle_pct: samples.map(() => 100),
    brake: samples.map(() => false),
    rpm: samples.map(() => 11000),
    gear: samples.map(() => 7),
    drs: null,
    x: samples.map((index) => index * 1000),
    y: samples.map((index) => index)
  };
}

// Antonelli is in the timing and the telemetry and not in the fixture's
// driver list, which has two drivers.
const LAPS = [
  lap("RUS", 1, 80_000),
  lap("RUS", 2, 70_500),
  lap("RUS", 3, 70_100),
  lap("VER", 1, 80_500),
  lap("VER", 2, 70_300),
  lap("VER", 3, 70_900),
  lap("ANT", 1, 81_000),
  lap("ANT", 2, 70_800)
];

const TELEMETRY_DRIVERS = ["RUS", "VER", "ANT"];
const lapsOf = (code) => LAPS.filter((row) => row.driver_code === code);

/** telemetry/index.json: each driver's laps as parallel arrays, and the driver's file. */
const TELEMETRY_INDEX = {
  channels: ["time_ms", "distance_m", "speed_kph", "throttle_pct", "brake", "rpm", "gear", "x", "y"],
  max_samples_per_lap: 300,
  drivers: TELEMETRY_DRIVERS.map((code) => ({
    driver_code: code,
    path: `telemetry/${code}.json`,
    lap_number: lapsOf(code).map((row) => row.lap_number),
    lap_time_ms: lapsOf(code).map((row) => row.lap_time_ms),
    compound: lapsOf(code).map((row) => row.compound),
    sample_count: lapsOf(code).map(() => 5),
    raw_sample_count: lapsOf(code).map(() => 5),
    has_position: lapsOf(code).map(() => true)
  }))
};

/** telemetry/<code>.json: every lap of one driver. Lap n runs 17,000 + 100 n ms a kilometre. */
const driverTelemetry = (code) => ({
  driver_code: code,
  laps: lapsOf(code).map((row) => telemetryLap(row.lap_number, 17_000 + row.lap_number * 100))
});

/**
 * Every file a session page reads, in the smallest form each tab accepts,
 * added to the fixture's generation (which has the drivers, the results and
 * the summary). Each driver's telemetry is a file of its own.
 */
const SESSION_FILES = {
  "laps.json": LAPS,
  "stints.json": [{ driver_code: "RUS", stint: 1, compound: "MEDIUM", start_lap: 1, end_lap: 3, lap_count: 3 }],
  "pit-stops.json": [
    {
      driver_code: "RUS",
      lap_number: 3,
      entry_time_ms: 4_972_191,
      duration_ms: 21552,
      stationary_ms: 2400,
      pit_lane_ms: 21480,
      sources: { duration_ms: "timing", stationary_ms: "pit_stop_series", pit_lane_ms: "pit_stop_series" }
    }
  ],
  "weather.json": [{ time_ms: 38_376, lap_number: null, air_temp_c: 33.6, track_temp_c: 53.2, humidity_pct: 30.3, wind_speed_kph: 1.0, rainfall: false }],
  "race-control.json": [{ time_ms: 3_300_000, lap_number: 1, category: "Flag", message: "GREEN LIGHT - PIT EXIT OPEN", flag: "GREEN", scope: "Track" }],
  "position-replay.json": {
    interval_ms: 5000,
    time_ms: [3_425_000],
    lap_number: [1],
    drivers: [{ driver_code: "RUS", x: [1], y: [2], speed_kph: [200], distance_m: [0] }]
  },
  "analysis/lap-times.json": [{ name: "RUS", x: [1, 2, 3], y: [80_000, 70_500, 70_100], color: "#27F4D2" }],
  "analysis/race-pace.json": {
    drivers: [
      {
        driver_code: "RUS",
        compound: "MEDIUM",
        stint: null,
        lap_count: 2,
        median_lap_ms: 70_300,
        mean_lap_ms: 70_300,
        trimmed_mean_lap_ms: 70_300,
        fastest_clean_lap_ms: 70_100,
        gap_to_best_ms: 0
      }
    ],
    stints: [],
    caveats: []
  },
  "analysis/tyre-degradation.json": {
    model: {
      method: "Theil-Sen residual filter followed by ordinary least squares",
      minimum_laps: 8,
      max_slope_standard_error_ms_per_lap: 20,
      max_slope_relative_standard_error: 0.25,
      race_fuel_correction_ms_per_lap: 55,
      sprint_fuel_correction_ms_per_lap: 35
    },
    rows: [],
    caveats: []
  },
  "analysis/team-mate-comparison.json": { rows: [], caveats: [] },
  "analysis/strategy.json": {
    compound_usage: { MEDIUM: 1 },
    pit_lane_time: { median_ms: 21552, fastest_ms: 21552, slowest_ms: 21552, timed_stop_count: 1, stop_count: 1 },
    pit_loss: {
      estimate_ms: null,
      spread_ms: null,
      qualifying_stop_count: 0,
      stop_count: 1,
      minimum_stop_count: 3,
      baseline_window_laps: 5,
      excluded_stop_counts: { too_few_baseline_laps: 1 },
      stops: []
    },
    pit_loss_estimate_ms: null,
    undercut_overcut: [],
    caveats: []
  },
  "analysis/track-dominance.json": { representative_laps: [], excluded_drivers: [], minisector_count: 0, minisectors: [], caveats: [] },
  "analysis/corner-analysis.json": { corner_source: "official", representative_laps: [], corners: [], caveats: [] },
  "analysis/car-performance.json": { drivers: [], teams: [], caveats: [] },
  // A race is published without this file; it is here so that the tab's
  // reader has all six of its analyses to read.
  "analysis/pace-prediction.json": { available: false, session_type: "Race", drivers: [], teams: [], caveats: [] },
  "telemetry/index.json": TELEMETRY_INDEX,
  ...Object.fromEntries(TELEMETRY_DRIVERS.map((code) => [`telemetry/${code}.json`, driverTelemetry(code)]))
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
  telemetry: { required: ["telemetry/index.json", "drivers.json"], optional: [] },
  "position-replay": { required: ["position-replay.json", "drivers.json"], optional: [] },
  weather: { required: ["weather.json"], optional: [] },
  "race-control": { required: ["race-control.json"], optional: [] },
  results: { required: ["results.json", "drivers.json"], optional: [] }
};

// The telemetry tab also reads the files of the two drivers it compares first.
const FIRST_COMPARISON = ["telemetry/RUS.json", "telemetry/VER.json"];

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
  // Seven tabs read the drivers and two read the laps.
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

  // The telemetry tab is among them: a lap is chosen from the telemetry index, which has its time.
  assert.deepEqual(available, ["lap-times", "performance", "strategy", "telemetry", "position-replay", "weather", "race-control", "results"]);
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
  assert.equal(performance.sessionType, "R");
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
    "analysis/strategy.json": { compound_usage: {}, caveats: [] },
    "analysis/race-pace.json": { stints: [], caveats: [] },
    "analysis/tyre-degradation.json": { rows: "none", caveats: [] },
    "telemetry/index.json": { max_samples_per_lap: 300, drivers: [] },
    // The frames of format 1, which was a list.
    "position-replay.json": [{ frame_index: 0, positions: [] }]
  };
  const bucket = bucketOf();
  republish(bucket, { ...SESSION_FILES, ...wrong });
  const view = await clientOf(bucket).openSession(SESSION_KEY);

  assert.equal((await failureOf(readWeather(view))).code, "invalid_artifact");
  assert.equal((await failureOf(readOverview(view))).code, "invalid_artifact");
  assert.equal((await failureOf(readRacePace(view))).code, "invalid_artifact");
  assert.equal((await failureOf(readTelemetry(view))).code, "invalid_artifact");
  assert.match((await failureOf(readTelemetry(view))).message, /telemetry\/index\.json has no list of channels/);
  const strategy = await failureOf(readStrategy(view));
  assert.equal(strategy.code, "invalid_artifact");
  assert.match(strategy.message, /analysis\/strategy\.json has no list of undercut_overcut/);
  const replay = await failureOf(readPositionReplay(view));
  assert.equal(replay.code, "invalid_artifact");
  assert.match(replay.message, /position-replay\.json is not an object/);
  // The tabs that do not read those files are untouched.
  assert.equal((await readResults(view)).results.length, 2);
  assert.equal((await readRaceControl(view)).length, 1);
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

// The largest file a page reads, and the one a reader comes back to most.
test("a driver's telemetry is kept by a shared view like any other file", async () => {
  const { view, requested } = await wholeSession({ share: true });

  const first = await view.read("telemetry/RUS.json");
  const second = await view.read("telemetry/RUS.json");
  await view.read("telemetry/index.json");
  await view.read("telemetry/index.json");

  assert.equal(first, second);
  assert.deepEqual(requested(), ["telemetry/RUS.json", "telemetry/index.json"]);
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

const INDEXED = telemetryLaps(TELEMETRY_INDEX);

test("the index's parallel arrays read as one row for each lap", () => {
  assert.equal(INDEXED.length, LAPS.length);
  assert.deepEqual(INDEXED[2], { driver_code: "RUS", lap_number: 3, lap_time_ms: 70_100, compound: "MEDIUM" });
  assert.deepEqual(INDEXED.at(-1), { driver_code: "ANT", lap_number: 2, lap_time_ms: 70_800, compound: "MEDIUM" });
});

test("the first comparison is the fastest lap of each of the two quickest drivers", () => {
  assert.deepEqual(defaultComparison(INDEXED), [
    { driver: "RUS", lap: 3 },
    { driver: "VER", lap: 2 }
  ]);
});

test("a lap without telemetry cannot be the lap compared", () => {
  const withoutRussellsBest = INDEXED.filter((entry) => !(entry.driver_code === "RUS" && entry.lap_number === 3));

  assert.deepEqual(defaultComparison(withoutRussellsBest), [
    { driver: "VER", lap: 2 },
    { driver: "RUS", lap: 2 }
  ]);
});

test("without lap times the first comparison is the first lap of two different drivers", () => {
  const untimed = INDEXED.map((entry) => ({ ...entry, lap_time_ms: null }));

  assert.deepEqual(defaultComparison(untimed), [
    { driver: "RUS", lap: 1 },
    { driver: "VER", lap: 1 }
  ]);
});

test("one driver's laps are compared with each other, and one lap with nothing", () => {
  const russell = INDEXED.filter((entry) => entry.driver_code === "RUS");
  const untimed = russell.map((entry) => ({ ...entry, lap_time_ms: null }));

  assert.deepEqual(defaultComparison(untimed), [
    { driver: "RUS", lap: 1 },
    { driver: "RUS", lap: 2 }
  ]);
  assert.equal(defaultComparison(russell.slice(0, 1)), null);
  assert.equal(defaultComparison([]), null);
});

test("the telemetry tab opens on the index and the files of the two drivers it compares", async () => {
  const { view, requested } = await wholeSession({ share: true });

  const telemetry = await readTelemetry(view);

  assert.equal(telemetry.laps.length, LAPS.length);
  assert.deepEqual(telemetry.pair, [
    { driver: "RUS", lap: 3 },
    { driver: "VER", lap: 2 }
  ]);
  assert.equal(telemetry.notice, null);
  // What the comparison says of a lap comes from the index and the driver list.
  assert.deepEqual(telemetry.comparison.driver_a, {
    driver_code: "RUS",
    team: "Mercedes",
    lap_time_ms: 70_100,
    compound: "MEDIUM",
    lap_number: 3
  });
  assert.equal(telemetry.comparison.driver_b.team, "Red Bull");
  assert.deepEqual(telemetry.comparison.distance_m, [0, 1000, 2000, 3000, 4000]);
  // Russell's lap 3 runs 17,300 ms a kilometre and Verstappen's lap 2 17,200.
  assert.deepEqual(telemetry.comparison.delta_time_ms, [0, -100, -200, -300, -400]);
  // The session has no DRS channel, and the comparison has none to chart.
  assert.equal(telemetry.comparison.drs_a, null);
  // Neither the laps of the session nor any other driver's telemetry.
  assert.deepEqual(requested().sort(), ["drivers.json", "telemetry/index.json", ...FIRST_COMPARISON].sort());
});

test("a driver's file is requested the first time one of their laps is compared, and never again", async () => {
  const { view, requested, forget } = await wholeSession({ share: true });
  await readTelemetry(view);
  forget();

  // Other laps of the two drivers the tab opened on: nothing to fetch.
  const same = await compareTelemetry(view, { driver: "VER", lap: 3 }, { driver: "RUS", lap: 2 });
  assert.equal(same.driver_a.driver_code, "VER");
  assert.equal(same.driver_a.lap_time_ms, 70_900);
  assert.equal(same.driver_b.lap_number, 2);
  assert.deepEqual(requested(), []);

  // A third driver: their file, once.
  const third = await compareTelemetry(view, { driver: "ANT", lap: 2 }, { driver: "RUS", lap: 3 });
  assert.equal(third.driver_a.lap_time_ms, 70_800);
  // The telemetry lists a driver the driver list does not: no team, and still compared.
  assert.equal(third.driver_a.team, null);
  assert.deepEqual(requested(), ["telemetry/ANT.json"]);

  // Two laps of one driver are one file.
  const own = await compareTelemetry(view, { driver: "ANT", lap: 1 }, { driver: "ANT", lap: 2 });
  assert.deepEqual(own.delta_time_ms, [0, 100, 200, 300, 400]);
  assert.deepEqual(requested(), ["telemetry/ANT.json"]);
});

test("a lap the index does not list compares to a notice, before any driver's file is asked for", async () => {
  const { view, requested, forget } = await wholeSession({ share: true });
  await readTelemetry(view);
  forget();

  const result = await compareTelemetry(view, { driver: "RUS", lap: 99 }, { driver: "ANT", lap: 2 });

  assert.deepEqual(result, { reason: "Telemetry is unavailable for one or both selected laps." });
  assert.deepEqual(requested(), []);
  assert.deepEqual(await compareTelemetry(view, { driver: "HAM", lap: 1 }, { driver: "RUS", lap: 2 }), {
    reason: "Telemetry is unavailable for one or both selected laps."
  });
});

test("a first comparison that cannot be loaded leaves the tab open, with the reason", async () => {
  const { bucket, view, generation } = await wholeSession({ share: true });
  const fileKey = `${generationPrefix(generation)}telemetry/RUS.json`;
  bucket.fault = (key) => (key === fileKey ? new Response("Service Unavailable", { status: 503 }) : undefined);

  const telemetry = await readTelemetry(view);

  assert.equal(telemetry.laps.length, LAPS.length);
  assert.equal(telemetry.comparison, null);
  assert.equal(telemetry.notice.reason, "The telemetry of RUS lap 3 and VER lap 2 could not be loaded.");
  assert.match(telemetry.notice.action, /telemetry\/RUS\.json answered 503/);
  // The failed read is not kept: the same driver compares once the outage is over.
  bucket.fault = () => undefined;
  assert.equal((await compareTelemetry(view, { driver: "RUS", lap: 2 }, { driver: "VER", lap: 2 })).driver_a.lap_number, 2);
});

test("an index that names a file the generation does not hold says so in the tab", async () => {
  const { view } = await wholeSession({ share: true, without: ["telemetry/VER.json"] });

  const telemetry = await readTelemetry(view);

  assert.equal(telemetry.comparison, null);
  assert.match(telemetry.notice.action, /telemetry\/VER\.json is not one of the files of this session's published generation/);
});

test("a driver's file without a lap the index lists is reported as that, not as an empty chart", async () => {
  const bucket = bucketOf();
  const short = driverTelemetry("RUS");
  short.laps = short.laps.filter((item) => item.lap_number !== 3);
  republish(bucket, { ...SESSION_FILES, "telemetry/RUS.json": short });
  const view = shareReads(await clientOf(bucket).openSession(SESSION_KEY));

  const telemetry = await readTelemetry(view);

  assert.equal(telemetry.comparison, null);
  assert.equal(telemetry.notice.reason, "The telemetry of RUS lap 3 is listed for this session and is not in RUS's file.");
});

test("a driver's file that is not a driver's telemetry is invalid", async () => {
  const bucket = bucketOf();
  republish(bucket, { ...SESSION_FILES, "telemetry/RUS.json": [] });
  const view = shareReads(await clientOf(bucket).openSession(SESSION_KEY));

  const failure = await failureOf(compareTelemetry(view, { driver: "RUS", lap: 3 }, { driver: "VER", lap: 2 }));

  assert.equal(failure.code, "invalid_artifact");
  assert.match(failure.message, /telemetry\/RUS\.json is not an object/);
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

test("a session with no telemetry laps opens to a notice and requests no driver's file", async () => {
  const bucket = bucketOf();
  const generation = republish(bucket, { ...SESSION_FILES, "telemetry/index.json": { ...TELEMETRY_INDEX, drivers: [] } });
  const view = shareReads(await clientOf(bucket).openSession(SESSION_KEY));
  bucket.requests.length = 0;

  const telemetry = await readTelemetry(view);

  assert.deepEqual(telemetry.laps, []);
  assert.equal(telemetry.pair, null);
  assert.equal(telemetry.comparison, null);
  assert.match(telemetry.notice.reason, /needs two laps with telemetry/);
  assert.deepEqual(
    bucket.keys().map((key) => key.slice(generationPrefix(generation).length)).sort(),
    ["drivers.json", "telemetry/index.json"]
  );
});

// The fixture is what the publisher writes: one driver, one lap.
test("the telemetry the publisher writes is read, and one lap is not a comparison", async () => {
  const view = shareReads(await clientOf(bucketOf()).openSession(SESSION_KEY));

  const telemetry = await readTelemetry(view);

  assert.deepEqual(telemetry.laps, [{ driver_code: "RUS", lap_number: 2, lap_time_ms: 72_037, compound: "MEDIUM" }]);
  assert.equal(telemetry.pair, null);
  assert.match(telemetry.notice.reason, /needs two laps with telemetry/);
  // The one lap compared with itself: the file reads as the schema types it.
  // Its four samples are three at the start of the lap and one at the end,
  // 71 seconds later, which is a hole: nothing is drawn across it.
  const own = await compareTelemetry(view, { driver: "RUS", lap: 2 }, { driver: "RUS", lap: 2 });
  assert.deepEqual(own.distance_m, [0, 22.2, 41.9, 2112.75, 4183.6]);
  assert.deepEqual(own.speed_a, [299, 299, 296, null, 303]);
  assert.deepEqual(own.delta_time_ms, [0, 0, 0, null, 0]);
  assert.equal(own.track.length, 4);
});
