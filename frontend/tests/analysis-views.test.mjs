import assert from "node:assert/strict";
import test from "node:test";

import { cornerName, cornerPlace, cornerSourceNote, minisectorTally, noBrakePoint, unavailableAnalyses } from "../src/lib/performance-view.ts";
import { teammateBasis, teammateGap, teammateGapText } from "../src/lib/teammate-view.ts";
import { formatRate, reportedFitCount, tyreFit, tyreFitLabel } from "../src/lib/tyre-chart.ts";

// ---------------------------------------------------------------------------
// Tyre degradation fits
// ---------------------------------------------------------------------------

/** A degradation row as the analysis writes it: every field, whatever the status. */
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

// The format gives a rate with every good fit. A row that breaks that is
// shown as having no rate, never as a rate of nothing.
test("a fit marked good that holds no rate is shown as having none", () => {
  const row = fit("ok", { degradation_ms_per_lap: null });

  assert.deepEqual(tyreFit(row), { status: "not_reported", reason: "No rate was published for this stint." });
  assert.equal(tyreFitLabel(tyreFit(row)), "No rate");
});

test("a good fit without a standard error still has its rate", () => {
  assert.deepEqual(tyreFit(fit("ok", { slope_standard_error_ms_per_lap: null })), {
    status: "reported",
    rate_ms_per_lap: 98.42,
    standard_error_ms_per_lap: null
  });
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

/** A team row as the analysis writes it. */
function team(overrides = {}) {
  return {
    team: "Williams",
    caveat: null,
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

// The 2025 Canadian GP, as published: Russell 1:15.5212, Antonelli 1:15.5213.
test("a gap too small to print is level, not one driver quicker by nothing", () => {
  for (const gap of [0.1, 0.4, -0.3]) {
    const row = team({ gap_ms: gap });
    assert.deepEqual(teammateGap(row), { status: "level", drivers: ["SAI", "ALB"] }, String(gap));
    assert.equal(teammateGapText(teammateGap(row)), "Level");
  }
  // From half a millisecond it prints as a thousandth, and is a gap.
  assert.equal(teammateGapText(teammateGap(team({ gap_ms: 0.5 }))), "SAI quicker by 0.001s");
  assert.equal(teammateGapText(teammateGap(team({ gap_ms: -0.7 }))), "ALB quicker by 0.001s");
});

test("a gap that arrives negative names the second driver as the quicker", () => {
  assert.deepEqual(teammateGap(team({ gap_ms: -90 })), { status: "reported", quicker: "ALB", slower: "SAI", gap_ms: 90 });
});

test("a team without two drivers has no gap", () => {
  const alone = [{ driver_code: "SAI", average_lap_ms: 72410.5, lap_count: 16, clean_lap_count: 20 }];

  assert.equal(teammateGap(team({ drivers: alone })).status, "none");
  assert.equal(teammateGap(team({ drivers: [] })).status, "none");
});

test("no gap and no caveat still reads as no gap, in words", () => {
  assert.deepEqual(teammateGap(team({ gap_ms: null })), { status: "none", reason: "No gap was published for this team." });
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
    representative_laps: [],
    excluded_drivers: [],
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

// A driver has no time in a minisector where their telemetry has a hole at
// a boundary, so the times object simply lacks them.
test("a driver missing from a minisector's times was not timed there", () => {
  const result = dominance([
    sector(1, "HAM", { HAM: 2023.5, VER: 2035.5 }),
    sector(2, "VER", { VER: 3090.1 }),
    sector(3, "VER", { VER: 1811.0 }),
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

const corner = (number, letter = null) => ({ corner_number: number, letter, distance_m: 282.5, x: 0, y: 0, drivers: [] });
const corners = (list, source = "official", caveats = []) => ({
  corner_source: source,
  representative_laps: [],
  corners: list,
  caveats
});

const SHOWN = {
  sessionType: "FP2",
  trackDominance: dominance([sector(1, "HAM", { HAM: 2023.5 })]),
  carPerformance: { drivers: [{ driver_code: "HAM", team: "Ferrari" }], teams: [], caveats: [] },
  cornerAnalysis: corners([corner(1)]),
  pacePrediction: { available: true, session_type: "Practice 2", drivers: [{ driver_code: "HAM", team: "Ferrari" }], teams: [], caveats: [] }
};

test("an analysis with something to show is not listed as missing", () => {
  assert.deepEqual(unavailableAnalyses(SHOWN), []);
});

test("an analysis the generation does not hold is said to be absent from the published data", () => {
  const notices = unavailableAnalyses({
    sessionType: "FP2",
    trackDominance: null,
    carPerformance: null,
    cornerAnalysis: null,
    pacePrediction: null
  });

  assert.deepEqual(
    notices.map((notice) => notice.title),
    ["Track dominance", "Car performance profile", "Corner analysis", "Race-pace prediction"]
  );
  assert.ok(notices.every((notice) => notice.reason === "Not part of this session's published data."));
});

// The prediction is published for practice sessions only. In a race its
// absence is how the format works, and is not reported as something missing.
test("a race without a pace prediction says the prediction is for practice, not that it is missing", () => {
  for (const sessionType of ["R", "S", "Q", "SQ"]) {
    const notices = unavailableAnalyses({ ...SHOWN, sessionType, pacePrediction: null });

    assert.deepEqual(notices, [
      { title: "Race-pace prediction", reason: "Made from practice long runs, so only a practice session has one." }
    ]);
  }
  for (const sessionType of ["FP1", "FP3", "fp2"]) {
    assert.equal(
      unavailableAnalyses({ ...SHOWN, sessionType, pacePrediction: null })[0].reason,
      "Not part of this session's published data."
    );
  }
});

test("an analysis that is published and empty gives the reason the analysis gave", () => {
  const notices = unavailableAnalyses({
    sessionType: "FP2",
    trackDominance: dominance([], { caveats: ["Method.", "No usable telemetry laps were available."] }),
    carPerformance: { drivers: [], teams: [], caveats: ["Method."] },
    cornerAnalysis: corners([], "inferred", ["Method.", "No braking events with a meaningful speed reduction were detected."]),
    pacePrediction: { available: false, session_type: "Practice 2", drivers: [], teams: [], caveats: ["Method.", "No long runs were found."] }
  });

  assert.deepEqual(notices, [
    { title: "Track dominance", reason: "No usable telemetry laps were available." },
    { title: "Car performance profile", reason: "No lap with usable telemetry." },
    { title: "Corner analysis", reason: "No braking events with a meaningful speed reduction were detected." },
    { title: "Race-pace prediction", reason: "No long runs were found." }
  ]);
});

// ---------------------------------------------------------------------------
// Corners
// ---------------------------------------------------------------------------

test("an official corner is a turn by the circuit's own number, with its letter", () => {
  assert.equal(cornerName(corner(1), "official"), "Turn 1");
  assert.equal(cornerName(corner(14, "A"), "official"), "Turn 14A");
  assert.match(cornerSourceNote("official"), /circuit's own corners/);
});

// Numbered in the order found, which is not the circuit's numbering: called a
// turn, the third braking zone of a lap would read as Turn 3.
test("an inferred corner is a braking zone, and is not given a turn number", () => {
  assert.equal(cornerName(corner(3), "inferred"), "Braking zone 3");
  assert.match(cornerSourceNote("inferred"), /could not be used/);
  assert.match(cornerSourceNote("inferred"), /not as the circuit numbers its turns/);
});

// Gasly into turn 9 on lap 56 of the 2026 Australian GP: F1's car feed has no
// brake reading for the 365 m before the corner, from 311 km/h to 218. The
// row has no brake point, and the page said "No braking".
test("a corner with no brake reading on the way in is not said to have been taken without braking", () => {
  assert.equal(noBrakePoint({ braking: "unread" }), "No brake reading");
  assert.equal(noBrakePoint({ braking: "none" }), "No braking");
  // Seen braking from where the reading came back: he braked, and it is not said that he may not have.
  assert.equal(noBrakePoint({ braking: "began_unread" }), "Braked, point not known");
  // A generation from before the analysis said which is read as it was.
  assert.equal(noBrakePoint({}), "No braking");
  // And one from when it said so with another word is read by that word: these are still
  // served while the sessions are rebuilt, and Gasly's row of one was "No braking" again.
  assert.equal(noBrakePoint({ brake_known: false }), "No brake reading");
  assert.equal(noBrakePoint({ brake_known: true }), "No braking");
  // Where both are there, the newer word is the one that is read.
  assert.equal(noBrakePoint({ braking: "none", brake_known: false }), "No braking");
  assert.equal(noBrakePoint({ braking: "began_unread", brake_known: false }), "Braked, point not known");
});

test("a corner row is placed where its own lap has the corner", () => {
  // Stroll's lap 30 of the 2026 Austrian GP has turn 6 at 2,554 m. The lap the corners
  // were placed on has it at 2,518 m, which was put beside his brake point.
  assert.equal(cornerPlace({ corner_distance_m: 2553.8 }), 2553.8);
  // A generation from before a row said where its own lap has the corner has nothing to show.
  assert.equal(cornerPlace({}), null);
  assert.equal(cornerPlace({ corner_distance_m: null }), null);
});
