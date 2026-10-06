import assert from "node:assert/strict";
import test from "node:test";

import {
  paceChange,
  pitLaneSummary,
  pitLossExclusionLabel,
  pitLossSummary,
  pitStopLog,
  stationarySummary
} from "../src/lib/strategy-view.ts";

/**
 * A pit stop as pit-stops.json has one. `feed` is what F1's pit-stop feed
 * says of it, `[stationary_ms, pit_lane_ms]`, or null for a stop the feed
 * does not report.
 */
function stop(driver, lap, duration, feed = null, entry = 4_972_191) {
  const [stationary, pitLane] = feed ?? [null, null];
  return {
    driver_code: driver,
    lap_number: lap,
    entry_time_ms: entry,
    duration_ms: duration,
    stationary_ms: stationary,
    pit_lane_ms: pitLane,
    sources: {
      duration_ms: duration === null ? null : "timing",
      stationary_ms: stationary === null ? null : "pit_stop_series",
      pit_lane_ms: pitLane === null ? null : "pit_stop_series"
    }
  };
}

const STOPS = [
  stop("NOR", 21, 21552, [2400, 21480]),
  stop("NOR", 47, 21905),
  stop("GAS", 13, 21603, [2150, 21590]),
  stop("PER", 4, null)
];

const stopLoss = (driver, lap, loss, reason = null) => ({
  driver_code: driver,
  lap_number: lap,
  pit_loss_ms: loss,
  excluded_reason: reason,
  in_lap_ms: null,
  out_lap_ms: null,
  baseline_lap_ms: null,
  baseline_lap_count: 0
});

/** A strategy analysis as analysis/strategy.json has one. */
function strategy(overrides = {}) {
  return {
    compound_usage: { MEDIUM: 31, HARD: 24 },
    pit_loss_estimate_ms: 21300.5,
    pit_loss: {
      estimate_ms: 21300.5,
      spread_ms: 412.3,
      qualifying_stop_count: 3,
      stop_count: 4,
      minimum_stop_count: 3,
      baseline_window_laps: 5,
      excluded_stop_counts: { missing_lap_time: 1 },
      stops: [
        stopLoss("NOR", 21, 21010.0),
        stopLoss("NOR", 47, 21300.5),
        stopLoss("GAS", 13, 21988.0),
        stopLoss("PER", 4, null, "missing_lap_time")
      ]
    },
    pit_lane_time: { median_ms: 21603.0, fastest_ms: 21552.0, slowest_ms: 21905.0, timed_stop_count: 3, stop_count: 4 },
    undercut_overcut: [],
    caveats: [],
    ...overrides
  };
}

const pitLoss = (fields) => ({
  estimate_ms: null,
  spread_ms: null,
  qualifying_stop_count: 0,
  stop_count: 0,
  minimum_stop_count: 3,
  baseline_window_laps: 5,
  excluded_stop_counts: {},
  stops: [],
  ...fields
});

// ---------------------------------------------------------------------------
// Pit loss
// ---------------------------------------------------------------------------

test("a published pit-loss estimate is reported with what it rests on", () => {
  assert.deepEqual(pitLossSummary(strategy()), {
    status: "estimated",
    estimate_ms: 21300.5,
    spread_ms: 412.3,
    qualifyingStopCount: 3,
    stopCount: 4
  });
});

test("too few qualifying stops is no estimate, with the counts that say why", () => {
  const few = strategy({
    pit_loss_estimate_ms: null,
    pit_loss: pitLoss({ qualifying_stop_count: 2, stop_count: 5 })
  });

  assert.deepEqual(pitLossSummary(few), {
    status: "too_few_stops",
    qualifyingStopCount: 2,
    stopCount: 5,
    minimumStopCount: 3
  });
});

test("a session without stops has no estimate and is not called short of stops", () => {
  const none = strategy({ pit_loss_estimate_ms: null, pit_loss: pitLoss({}) });

  assert.deepEqual(pitLossSummary(none), { status: "no_stops" });
});

test("a session without the analysis has no pit loss, and says it was not published", () => {
  assert.deepEqual(pitLossSummary(null), { status: "not_published" });
});

// ---------------------------------------------------------------------------
// Entry to exit, from the timing
// ---------------------------------------------------------------------------

test("the pit-lane summary is the analysis's own when the session has one", () => {
  assert.deepEqual(pitLaneSummary(strategy(), STOPS), {
    median_ms: 21603,
    fastest_ms: 21552,
    slowest_ms: 21905,
    timedStopCount: 3,
    stopCount: 4
  });
});

test("without the analysis it is worked out from the stops, the same way", () => {
  assert.deepEqual(pitLaneSummary(null, STOPS), {
    median_ms: 21603,
    fastest_ms: 21552,
    slowest_ms: 21905,
    timedStopCount: 3,
    stopCount: 4
  });
});

// One car held in the lane must not set the figure, which is why it is a median.
test("the median is not moved by one car parked in the pit lane", () => {
  const held = [stop("A", 1, 21000), stop("B", 2, 22000), stop("C", 3, 23000), stop("D", 4, 24000), stop("E", 5, 410846)];
  const even = held.slice(0, 4);

  assert.equal(pitLaneSummary(null, held).median_ms, 23000);
  assert.equal(pitLaneSummary(null, held).slowest_ms, 410846);
  assert.equal(pitLaneSummary(null, even).median_ms, 22500);
});

test("stops the car did not come back out of give no pit-lane time", () => {
  assert.deepEqual(pitLaneSummary(null, [stop("PER", 4, null)]), {
    median_ms: null,
    fastest_ms: null,
    slowest_ms: null,
    timedStopCount: 0,
    stopCount: 1
  });
});

// ---------------------------------------------------------------------------
// Stationary time, from F1's pit-stop feed
// ---------------------------------------------------------------------------

test("stationary time is summarised over the stops F1's feed reports, and says how many those are", () => {
  assert.deepEqual(stationarySummary(STOPS), {
    median_ms: 2275,
    fastest: { driver_code: "GAS", lap_number: 13, stationary_ms: 2150 },
    timedStopCount: 2,
    stopCount: 4
  });
});

test("a session F1's feed reports no stop of has no stationary time, not a zero", () => {
  assert.deepEqual(stationarySummary([stop("NOR", 21, 21552), stop("PER", 4, null)]), {
    median_ms: null,
    fastest: null,
    timedStopCount: 0,
    stopCount: 2
  });
  assert.deepEqual(stationarySummary([]), { median_ms: null, fastest: null, timedStopCount: 0, stopCount: 0 });
});

// ---------------------------------------------------------------------------
// The pit stop log
// ---------------------------------------------------------------------------

test("each stop carries every figure under its own name, and its pit loss", () => {
  const log = pitStopLog(strategy(), STOPS);

  assert.deepEqual(log[0], {
    driver_code: "NOR",
    lap_number: 21,
    entry_time_ms: 4_972_191,
    stationary_ms: 2400,
    pit_lane_ms: 21480,
    duration_ms: 21552,
    pitLoss: { status: "estimated", pit_loss_ms: 21010 }
  });
  // A stop F1's feed does not report, and that the car did not come back from.
  assert.deepEqual(log[3], {
    driver_code: "PER",
    lap_number: 4,
    entry_time_ms: 4_972_191,
    stationary_ms: null,
    pit_lane_ms: null,
    duration_ms: null,
    pitLoss: { status: "excluded", reason: "missing_lap_time" }
  });
});

test("a pit loss is matched to its stop by driver and lap, not by position in the list", () => {
  const shuffled = strategy();
  shuffled.pit_loss.stops.reverse();

  assert.deepEqual(
    pitStopLog(shuffled, STOPS).map((row) => row.pitLoss?.pit_loss_ms ?? row.pitLoss?.reason),
    [21010, 21300.5, 21988, "missing_lap_time"]
  );
});

test("the stops listed are the stop list's, whatever the analysis mentions", () => {
  const partial = strategy();
  partial.pit_loss.stops = [stopLoss("NOR", 21, 21010.0), stopLoss(null, null, null, "no_lap_number")];

  const log = pitStopLog(partial, STOPS);

  assert.equal(log.length, 4);
  assert.deepEqual(log.map((row) => row.pitLoss?.status ?? null), ["estimated", null, null, null]);
});

test("without the analysis the log still lists every stop", () => {
  const log = pitStopLog(null, STOPS);

  assert.equal(log.length, 4);
  assert.ok(log.every((row) => row.pitLoss === null));
});

test("a stop only F1's feed reports has no entry time on the session clock", () => {
  const log = pitStopLog(null, [stop("NOR", 21, null, [2400, 21480], null)]);

  assert.equal(log[0].entry_time_ms, null);
  assert.equal(log[0].stationary_ms, 2400);
});

test("each reason a stop is left out of the estimate is worded", () => {
  assert.equal(pitLossExclusionLabel("not_green"), "not under green");
  assert.equal(pitLossExclusionLabel("first_lap"), "stopped on lap 1");
  assert.equal(pitLossExclusionLabel("too_few_baseline_laps"), "too few clean laps around it");
});

// ---------------------------------------------------------------------------
// Pace change across a stop
// ---------------------------------------------------------------------------

// The figure is the lap before minus the lap after. The page used to say
// "negative is quicker" and colour a negative value as the good one.
test("a positive pace change is quicker on the new tyres", () => {
  // Norris in the published race: 1,507 ms quicker after his first stop.
  assert.deepEqual(paceChange({ first_clean_lap_gain_ms: 1507 }), {
    direction: "quicker",
    change_ms: 1507,
    text: "1.507s quicker"
  });
});

test("a negative pace change is slower on the new tyres", () => {
  assert.deepEqual(paceChange({ first_clean_lap_gain_ms: -332 }), {
    direction: "slower",
    change_ms: 332,
    text: "0.332s slower"
  });
});

test("the direction always agrees with before minus after", () => {
  for (const [before, after, direction] of [
    [72_000, 71_000, "quicker"],
    [71_000, 72_000, "slower"],
    [71_500, 71_500, "level"]
  ]) {
    assert.equal(paceChange({ first_clean_lap_gain_ms: before - after }).direction, direction);
  }
});

test("no pair of laps to compare is no pace change, not a change of zero", () => {
  assert.deepEqual(paceChange({ first_clean_lap_gain_ms: null }), { direction: "none", change_ms: null, text: "--" });
  assert.equal(paceChange({ first_clean_lap_gain_ms: 0 }).direction, "level");
});
