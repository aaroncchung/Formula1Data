import assert from "node:assert/strict";
import test from "node:test";

import {
  paceChange,
  pitLaneSummary,
  pitLossExclusionLabel,
  pitLossSummary,
  pitStopLog
} from "../src/lib/strategy-view.ts";

function stop(driver, lap, duration, entry = "0 days 01:22:52.191000") {
  return { session_id: "2026-08-r", driver_code: driver, lap_number: lap, duration_ms: duration, local_time: entry };
}

const STOPS = [stop("NOR", 21, 21552), stop("NOR", 47, 21905), stop("GAS", 13, 21603), stop("PER", 4, null)];

/** A strategy artifact as `calculate_strategy` writes it from pipeline version 2. */
function strategy(overrides = {}) {
  return {
    session_id: "2026-08-r",
    stints: [],
    compound_usage: { MEDIUM: 31, HARD: 24 },
    pit_stops: STOPS,
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
        { driver_code: "NOR", lap_number: 21, pit_loss_ms: 21010.0, excluded_reason: null },
        { driver_code: "NOR", lap_number: 47, pit_loss_ms: 21300.5, excluded_reason: null },
        { driver_code: "GAS", lap_number: 13, pit_loss_ms: 21988.0, excluded_reason: null },
        { driver_code: "PER", lap_number: 4, pit_loss_ms: null, excluded_reason: "missing_lap_time" }
      ]
    },
    pit_lane_time: { median_ms: 21603.0, fastest_ms: 21552.0, slowest_ms: 21905.0, timed_stop_count: 3, stop_count: 4 },
    undercut_overcut: [],
    race_control_overlays: [],
    caveats: [],
    ...overrides
  };
}

/**
 * The same artifact as pipeline version 1 wrote it: no `pit_loss` and no
 * `pit_lane_time`, and the mean pit-lane time in `pit_loss_estimate_ms`.
 */
function oldStrategy() {
  const old = strategy({ pit_loss_estimate_ms: 21921.9 });
  delete old.pit_loss;
  delete old.pit_lane_time;
  return old;
}

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
    pit_loss: { estimate_ms: null, spread_ms: null, qualifying_stop_count: 2, stop_count: 5, minimum_stop_count: 3, stops: [] }
  });

  assert.deepEqual(pitLossSummary(few), {
    status: "too_few_stops",
    qualifyingStopCount: 2,
    stopCount: 5,
    minimumStopCount: 3
  });
});

test("a session without stops has no estimate and is not called short of stops", () => {
  const none = strategy({
    pit_stops: [],
    pit_loss_estimate_ms: null,
    pit_loss: { estimate_ms: null, spread_ms: null, qualifying_stop_count: 0, stop_count: 0, stops: [] }
  });

  assert.deepEqual(pitLossSummary(none), { status: "no_stops" });
});

// Before pipeline version 2 this field held the mean pit-lane time, which is
// not what a stop costs: it has no on-track baseline in it.
test("the old mean pit-lane time is never shown as a pit loss", () => {
  const old = oldStrategy();
  assert.equal(old.pit_loss_estimate_ms, 21921.9);

  assert.deepEqual(pitLossSummary(old), { status: "not_published" });
  assert.deepEqual(pitLossSummary(null), { status: "not_published" });
});

// ---------------------------------------------------------------------------
// Pit-lane time
// ---------------------------------------------------------------------------

test("pit-lane time is taken from the artifact when it has it", () => {
  assert.deepEqual(pitLaneSummary(strategy(), STOPS), {
    median_ms: 21603,
    fastest_ms: 21552,
    slowest_ms: 21905,
    timedStopCount: 3,
    stopCount: 4
  });
});

test("pit-lane time is worked out from the stops when the artifact has none", () => {
  const expected = { median_ms: 21603, fastest_ms: 21552, slowest_ms: 21905, timedStopCount: 3, stopCount: 4 };

  assert.deepEqual(pitLaneSummary(oldStrategy(), STOPS), expected);
  assert.deepEqual(pitLaneSummary(null, STOPS), expected);
});

// One car held in the lane must not set the figure, which is why it is a median.
test("the median is not moved by one car parked in the pit lane", () => {
  const held = [stop("A", 1, 21000), stop("B", 2, 22000), stop("C", 3, 23000), stop("D", 4, 24000), stop("E", 5, 410846)];
  const even = held.slice(0, 4);

  assert.equal(pitLaneSummary(null, held).median_ms, 23000);
  assert.equal(pitLaneSummary(null, held).slowest_ms, 410846);
  assert.equal(pitLaneSummary(null, even).median_ms, 22500);
});

test("stops without a recorded transit give no pit-lane time", () => {
  assert.deepEqual(pitLaneSummary(null, [stop("PER", 4, null)]), {
    median_ms: null,
    fastest_ms: null,
    slowest_ms: null,
    timedStopCount: 0,
    stopCount: 1
  });
});

// ---------------------------------------------------------------------------
// The pit stop log
// ---------------------------------------------------------------------------

test("each stop carries its pit-lane time, its entry on the session clock, and its pit loss", () => {
  const log = pitStopLog(strategy(), STOPS);

  assert.deepEqual(log[0], {
    driver_code: "NOR",
    lap_number: 21,
    duration_ms: 21552,
    entry_clock_ms: 4_972_191,
    pitLoss: { status: "estimated", pit_loss_ms: 21010 }
  });
  assert.deepEqual(log[3], {
    driver_code: "PER",
    lap_number: 4,
    duration_ms: null,
    entry_clock_ms: 4_972_191,
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

test("without a per-stop estimate the log still lists every stop", () => {
  for (const source of [oldStrategy(), null]) {
    const log = pitStopLog(source, STOPS);

    assert.equal(log.length, 4);
    assert.ok(log.every((row) => row.pitLoss === null));
  }
});

test("a pit entry that is not a duration has no clock time", () => {
  const log = pitStopLog(null, [stop("NOR", 21, 21552, "NaT"), stop("NOR", 47, 21905, null)]);

  assert.deepEqual(log.map((row) => row.entry_clock_ms), [null, null]);
});

test("each reason a stop is left out is worded, and an unknown one is still readable", () => {
  assert.equal(pitLossExclusionLabel("not_green"), "not under green");
  assert.equal(pitLossExclusionLabel("first_lap"), "stopped on lap 1");
  assert.equal(pitLossExclusionLabel("too_few_baseline_laps"), "too few clean laps around it");
  assert.equal(pitLossExclusionLabel("some_new_reason"), "some new reason");
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
  for (const gain of [null, undefined, Number.NaN]) {
    assert.deepEqual(paceChange({ first_clean_lap_gain_ms: gain }), { direction: "none", change_ms: null, text: "--" });
  }
  assert.deepEqual(paceChange({}), { direction: "none", change_ms: null, text: "--" });
  assert.equal(paceChange({ first_clean_lap_gain_ms: 0 }).direction, "level");
});
