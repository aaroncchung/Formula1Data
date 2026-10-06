import assert from "node:assert/strict";
import test from "node:test";

import { minisectorTally, unavailableAnalyses } from "../src/lib/performance-view.ts";
import { teammateBasis, teammateGap, teammateGapText } from "../src/lib/teammate-view.ts";
import { formatRate, reportedFitCount, tyreFit, tyreFitLabel } from "../src/lib/tyre-chart.ts";

// ---------------------------------------------------------------------------
// Tyre degradation fits
// ---------------------------------------------------------------------------

/** A degradation row as pipeline version 2 writes it: every field, whatever the status. */
function fit(status, overrides = {}) {
  const reported = status === "ok";
  return {
    driver_code: "RUS",
    compound: "MEDIUM",
    stint: 1,
    sample_count: 18,
    stint_length: 21,
    degradation_ms_per_lap: reported ? 98.42 : null,
    raw_slope_ms_per_lap: reported ? 43.42 : null,
    fuel_correction_ms_per_lap: 55.0,
    r_squared: reported ? 0.61 : null,
    residual_spread_ms: reported ? 212.4 : null,
    slope_standard_error_ms_per_lap: reported ? 9.87 : null,
    excluded_outlier_count: 0,
    fit_status: status,
    caveats: reported ? ["Includes an assumed 55 ms/lap fuel-burn correction."] : [],
    ...overrides
  };
}

test("a fit the analysis reported holds a rate and its standard error", () => {
  assert.deepEqual(tyreFit(fit("ok")), {
    status: "reported",
    rate_ms_per_lap: 98.42,
    standard_error_ms_per_lap: 9.87
  });
  assert.equal(tyreFitLabel(tyreFit(fit("ok"))), "+98.4 ms/lap");
});

test("a poor fit is not presented as a rate, and says why in the publisher's words", () => {
  const reason = "No rate reported: the lap times scatter too much to fix the slope. Its standard error is 61 ms/lap, over the limit of 20 ms/lap or 25% of the slope.";
  const row = fit("poor_fit", { r_squared: 0.04, residual_spread_ms: 640.2, slope_standard_error_ms_per_lap: 61.3, caveats: [reason] });

  assert.deepEqual(tyreFit(row), { status: "poor_fit", reason });
  assert.equal(tyreFitLabel(tyreFit(row)), "No rate: laps too scattered");
});

test("a stint with too few laps is not presented as a rate", () => {
  const reason = "No rate reported: 5 clean laps, and at least 8 are required.";
  const row = fit("too_few_laps", { sample_count: 5, caveats: [reason] });

  assert.deepEqual(tyreFit(row), { status: "too_few_laps", reason });
  assert.equal(tyreFitLabel(tyreFit(row)), "No rate: too few laps");
});

// The status decides before the number does: a row that says its fit is poor
// must not be shown as a rate because a number was left in it.
test("an unreported status wins over a number in the rate field", () => {
  for (const status of ["poor_fit", "too_few_laps"]) {
    const row = fit(status, { degradation_ms_per_lap: 12.5, raw_slope_ms_per_lap: -42.5 });

    assert.equal(tyreFit(row).status, status);
    assert.doesNotMatch(tyreFitLabel(tyreFit(row)), /\d/);
  }
});

test("an unreported fit without a caveat still says why", () => {
  assert.match(tyreFit(fit("poor_fit")).reason, /scatter too much/);
  assert.match(tyreFit(fit("too_few_laps")).reason, /too few clean laps/);
});

// A generation built before pipeline version 2 has no `fit_status`.
test("a row from before fit statuses is a rate when it has one, and nothing when it has not", () => {
  const old = { driver_code: "NOR", compound: "MEDIUM", stint: 1, sample_count: 18, stint_length: 18, degradation_ms_per_lap: 108.6, raw_slope_ms_per_lap: 53.6, r_squared: 0.476, caveats: [] };

  assert.deepEqual(tyreFit(old), { status: "reported", rate_ms_per_lap: 108.6, standard_error_ms_per_lap: null });
  assert.deepEqual(tyreFit({ ...old, degradation_ms_per_lap: null }), {
    status: "not_reported",
    reason: "No rate was published for this stint."
  });
  assert.equal(tyreFit({ ...old, degradation_ms_per_lap: undefined }).status, "not_reported");
  assert.equal(tyreFitLabel(tyreFit({ ...old, degradation_ms_per_lap: null })), "No rate");
});

test("a status this build does not know is judged by whether the row holds a rate", () => {
  assert.equal(tyreFit(fit("ok", { fit_status: "reported" })).status, "reported");
  assert.equal(tyreFit(fit("ok", { fit_status: "something_new", degradation_ms_per_lap: null })).status, "not_reported");
});

test("a rate is written with its sign, and a negative one keeps it", () => {
  assert.equal(formatRate(98.42), "+98.4 ms/lap");
  assert.equal(formatRate(-12.34), "-12.3 ms/lap");
  assert.equal(formatRate(0), "0.0 ms/lap");
  assert.equal(formatRate(-0.04), "0.0 ms/lap");
  assert.equal(formatRate(null), "--");
  assert.equal(formatRate(undefined), "--");
});

test("the count of reported fits follows the drivers on screen", () => {
  const rows = [
    fit("ok", { driver_code: "RUS", stint: 1 }),
    fit("poor_fit", { driver_code: "RUS", stint: 2 }),
    fit("ok", { driver_code: "ANT", stint: 1 }),
    fit("too_few_laps", { driver_code: "HAM", stint: 1 })
  ];

  assert.equal(reportedFitCount(rows, ["RUS", "ANT", "HAM"]), 2);
  assert.equal(reportedFitCount(rows, ["RUS"]), 1);
  assert.equal(reportedFitCount(rows, ["HAM"]), 0);
  assert.equal(reportedFitCount(rows, []), 0);
});

// ---------------------------------------------------------------------------
// Team-mates
// ---------------------------------------------------------------------------

/** A team row as pipeline version 2 writes it. */
function team(overrides = {}) {
  return {
    team: "Williams",
    drivers: [
      { driver_code: "SAI", average_lap_ms: 72410.5, lap_count: 16, clean_lap_count: 20 },
      { driver_code: "ALB", average_lap_ms: 72565.5, lap_count: 16, clean_lap_count: 58 }
    ],
    gap_ms: 155.0,
    gap_spread_ms: 412.6,
    matched_lap_count: 18,
    trimmed_lap_count: 2,
    ...overrides
  };
}

test("the gap names the quicker driver, who is listed first", () => {
  const gap = teammateGap(team());

  assert.deepEqual(gap, { status: "reported", quicker: "SAI", slower: "ALB", gap_ms: 155 });
  assert.equal(teammateGapText(gap), "SAI quicker by 0.155s");
  assert.equal(teammateBasis(team()), "18 matched laps · 2 trimmed · lap-to-lap spread 0.413s");
});

test("too few matched laps is no gap, with the row's own reason, and not a gap of zero", () => {
  const caveat = "Only 3 matched clean laps; at least 5 are needed to report a gap.";
  const row = team({
    drivers: [
      { driver_code: "BOT", average_lap_ms: null, lap_count: 0, clean_lap_count: 3 },
      { driver_code: "PER", average_lap_ms: null, lap_count: 0, clean_lap_count: 3 }
    ],
    gap_ms: null,
    gap_spread_ms: null,
    matched_lap_count: 3,
    trimmed_lap_count: 0,
    caveat
  });

  assert.deepEqual(teammateGap(row), { status: "none", reason: caveat });
  assert.equal(teammateGapText(teammateGap(row)), "No gap");
  assert.equal(teammateBasis(row), "3 matched laps");
});

test("a dead heat is level, which is not the same as no gap", () => {
  assert.deepEqual(teammateGap(team({ gap_ms: 0 })), { status: "level", drivers: ["SAI", "ALB"] });
  assert.equal(teammateGapText(teammateGap(team({ gap_ms: 0 }))), "Level");
});

test("a gap that arrives negative names the second driver as the quicker", () => {
  assert.deepEqual(teammateGap(team({ gap_ms: -90 })), { status: "reported", quicker: "ALB", slower: "SAI", gap_ms: 90 });
});

test("a team without two drivers has no gap", () => {
  assert.equal(teammateGap(team({ drivers: [{ driver_code: "SAI", lap_count: 16 }] })).status, "none");
  assert.equal(teammateGap(team({ drivers: [] })).status, "none");
});

// A generation built before pipeline version 2: three fields per row.
test("a row from before matched laps still gives its gap, and says nothing about laps", () => {
  const old = {
    team: "McLaren",
    drivers: [
      { driver_code: "PIA", average_lap_ms: 71900.1, lap_count: 61 },
      { driver_code: "NOR", average_lap_ms: 72012.3, lap_count: 58 }
    ],
    gap_ms: 112.2
  };

  assert.equal(teammateGapText(teammateGap(old)), "PIA quicker by 0.112s");
  assert.equal(teammateBasis(old), null);
  assert.deepEqual(teammateGap({ ...old, gap_ms: undefined }), { status: "none", reason: "No gap was published for this team." });
});

test("one matched lap is counted in the singular and nothing trimmed is not mentioned", () => {
  assert.equal(teammateBasis(team({ matched_lap_count: 1, trimmed_lap_count: 0, gap_spread_ms: null })), "1 matched lap");
});

// ---------------------------------------------------------------------------
// Track dominance and the analyses with nothing to show
// ---------------------------------------------------------------------------

function sector(index, winner, times) {
  return {
    index,
    start_distance_m: (index - 1) * 170,
    end_distance_m: index * 170,
    midpoint: { x: index, y: index },
    winner_driver_code: winner,
    segment_time_ms: winner ? times[winner] : null,
    gap_to_next_ms: null,
    driver_times_ms: times
  };
}

function dominance(minisectors, overrides = {}) {
  return {
    session_id: "2026-08-r",
    representative_laps: [],
    minisector_count: minisectors.length,
    minisectors,
    caveats: ["Each driver's fastest clean lap with complete telemetry is compared."],
    ...overrides
  };
}

test("minisectors are counted for each winner, most wins first", () => {
  const result = dominance([
    sector(1, "HAM", { HAM: 2023.5, VER: 2035.5, ANT: 2032.3 }),
    sector(2, "VER", { HAM: 3100.0, VER: 3090.1, ANT: 3095.0 }),
    sector(3, "HAM", { HAM: 1800.2, VER: 1811.0, ANT: 1802.2 }),
    sector(4, "ANT", { HAM: 2500.0, VER: 2501.0, ANT: 2499.0 })
  ]);

  assert.deepEqual(minisectorTally(result), [
    { driver: "HAM", won: 2, timed: 4 },
    { driver: "ANT", won: 1, timed: 4 },
    { driver: "VER", won: 1, timed: 4 }
  ]);
});

// From pipeline version 2 a driver has no time in a minisector where their
// telemetry has a hole at a boundary, so the times object simply lacks them.
test("a driver missing from a minisector's times was not timed there", () => {
  const result = dominance([
    sector(1, "HAM", { HAM: 2023.5, VER: 2035.5 }),
    sector(2, "VER", { VER: 3090.1 }),
    sector(3, "VER", { VER: 1811.0, HAM: null }),
    sector(4, null, {})
  ]);

  assert.deepEqual(minisectorTally(result), [
    { driver: "VER", won: 2, timed: 3 },
    { driver: "HAM", won: 1, timed: 1 }
  ]);
});

test("an empty result has no tally", () => {
  assert.deepEqual(minisectorTally(dominance([])), []);
});

const SHOWN = {
  trackDominance: dominance([sector(1, "HAM", { HAM: 2023.5 })]),
  carPerformance: { session_id: "s", drivers: [{ driver_code: "HAM", team: "Ferrari" }], teams: [], caveats: [] },
  cornerAnalysis: { session_id: "s", representative_laps: [], corners: [{ corner_number: 1, distance_m: 282.5, x: 0, y: 0, drivers: [] }], caveats: [] },
  pacePrediction: { session_id: "s", available: true, session_type: "Practice 2", drivers: [{ driver_code: "HAM", team: "Ferrari" }], teams: [], caveats: [] }
};

test("an analysis with something to show is not listed as missing", () => {
  assert.deepEqual(unavailableAnalyses(SHOWN), []);
});

test("an analysis the generation does not hold is said to be absent from the published data", () => {
  const notices = unavailableAnalyses({ trackDominance: null, carPerformance: null, cornerAnalysis: null, pacePrediction: null });

  assert.deepEqual(
    notices.map((notice) => notice.title),
    ["Track dominance", "Car performance profile", "Corner analysis", "Race-pace prediction"]
  );
  assert.ok(notices.every((notice) => notice.reason === "Not part of this session's published data."));
});

test("an analysis that is published and empty gives the reason the analysis gave", () => {
  const notices = unavailableAnalyses({
    trackDominance: dominance([], { caveats: ["Method.", "No usable telemetry laps were available."] }),
    carPerformance: { session_id: "s", drivers: [], teams: [], caveats: ["Method."] },
    cornerAnalysis: { session_id: "s", representative_laps: [], corners: [], caveats: ["Method.", "No braking events with a meaningful speed reduction were detected."] },
    // What a race's artifact holds: the analysis is for practice sessions only.
    pacePrediction: { session_id: "s", available: false, session_type: "Race", drivers: [], teams: [], caveats: ["Method.", "Pace prediction is only produced for practice sessions."] }
  });

  assert.deepEqual(notices, [
    { title: "Track dominance", reason: "No usable telemetry laps were available." },
    { title: "Car performance profile", reason: "No lap with usable telemetry." },
    { title: "Corner analysis", reason: "No braking events with a meaningful speed reduction were detected." },
    { title: "Race-pace prediction", reason: "Pace prediction is only produced for practice sessions." }
  ]);
});
