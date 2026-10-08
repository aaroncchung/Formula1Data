/**
 * The published format, as TypeScript types.
 *
 * GENERATED from schema/published-v2.schema.json by `npm run types`
 * (scripts/published-types.mjs). Do not edit: change f1data/models.py, write
 * the schema again with `python -m f1data schema`, and run `npm run types`.
 * tests/published-types.test.mjs fails when this file and the schema differ.
 */

/**
 * Where the corners of a corner analysis come from.
 *
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "CornerSource".
 */
export type CornerSource = "official" | "inferred";
/**
 * analysis/lap-times.json: each driver's timed laps, ready to chart.
 */
export type LapTimes = LapTimeSeries[];
/**
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "Confidence".
 */
export type Confidence = "low" | "medium" | "high";
/**
 * A tyre compound, as F1's timing names it.
 *
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "Compound".
 */
export type Compound =
  "SOFT" | "MEDIUM" | "HARD" | "INTERMEDIATE" | "WET" | "SUPERSOFT" | "ULTRASOFT" | "HYPERSOFT";
/**
 * Why a stop is left out of the pit-loss estimate.
 *
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "PitLossExclusion".
 */
export type PitLossExclusion =
  | "no_lap_number"
  | "red_flag_wait"
  | "no_stop"
  | "missing_lap_time"
  | "first_lap"
  | "back_to_back_stops"
  | "not_green"
  | "too_few_baseline_laps";
/**
 * Whether a tyre degradation rate is reported for a stint, and if not, why.
 *
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "FitStatus".
 */
export type FitStatus = "ok" | "too_few_laps" | "poor_fit";
/**
 * Who placed the circuit's corners along the lap.
 *
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "DistanceSource".
 */
export type DistanceSource = "archive" | "telemetry";
/**
 * Something a session has to have to count as complete (f1data/coverage.py).
 *
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "CoverageBar".
 */
export type CoverageBar =
  | "session_info"
  | "driver_list"
  | "timing_data"
  | "tyre_data"
  | "track_status"
  | "lap_count"
  | "session_status"
  | "weather"
  | "race_control"
  | "car_data"
  | "position"
  | "pit_stop_series"
  | "circuit_info"
  | "classification"
  | "measurement";
/**
 * drivers.json: everyone in F1's driver list or the classification.
 */
export type Drivers = Driver[];
/**
 * laps.json: every lap of every driver, in timing order.
 */
export type Laps = Lap[];
/**
 * The session's code.
 *
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "SessionType".
 */
export type SessionType = "FP1" | "FP2" | "FP3" | "Q" | "SQ" | "S" | "R";
/**
 * pit-stops.json: every entry to the pit lane, with F1's own figures where it gives them.
 */
export type PitStops = PitStop[];
/**
 * race-control.json: race control's messages, in order.
 */
export type RaceControl = RaceControlMessage[];
/**
 * results.json: the classification in finishing order, then anyone it leaves out.
 */
export type Results = Result[];
/**
 * stints.json: each run of laps a driver did on one set of tyres.
 */
export type Stints = Stint[];
/**
 * A per-sample array of a telemetry lap.
 *
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "TelemetryChannel".
 */
export type TelemetryChannel =
  "time_ms" | "distance_m" | "speed_kph" | "throttle_pct" | "brake" | "rpm" | "gear" | "drs" | "x" | "y";
/**
 * weather.json: every weather sample F1 sent, about one a minute.
 */
export type Weather = WeatherSample[];
/**
 * drivers.json: everyone in F1's driver list or the classification.
 *
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "Drivers".
 */
export type Drivers1 = Driver[];
/**
 * analysis/lap-times.json: each driver's timed laps, ready to chart.
 *
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "LapTimes".
 */
export type LapTimes1 = LapTimeSeries[];
/**
 * laps.json: every lap of every driver, in timing order.
 *
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "Laps".
 */
export type Laps1 = Lap[];
/**
 * pit-stops.json: every entry to the pit lane, with F1's own figures where it gives them. Not every entry is a pit stop. One is known to be a stop when F1's pit-stop feed gives it a stationary time or its tyres were changed, and is taken not to be when the feed gives it none and the tyre data says the car kept its tyres.
 *
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "PitStops".
 */
export type PitStops1 = PitStop[];
/**
 * race-control.json: race control's messages, in order.
 *
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "RaceControl".
 */
export type RaceControl1 = RaceControlMessage[];
/**
 * results.json: the classification in finishing order, then anyone it leaves out.
 *
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "Results".
 */
export type Results1 = Result[];
/**
 * stints.json: each run of laps a driver did on one set of tyres.
 *
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "Stints".
 */
export type Stints1 = Stint[];
/**
 * weather.json: every weather sample F1 sent, about one a minute.
 *
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "Weather".
 */
export type Weather1 = WeatherSample[];

/**
 * Every object published under v2/, by its path there. Braces mark the parts of a path that vary. Generated from f1data/models.py by `python -m f1data schema`; do not edit. x-decimals on a number, or on an array of numbers, is how many decimal places it is rounded to.
 */
export interface Formula1DataPublishedFormat2 {
  "generations/{session_key}/{generation}/analysis/car-performance.json": CarPerformance;
  "generations/{session_key}/{generation}/analysis/corner-analysis.json": CornerAnalysis;
  "generations/{session_key}/{generation}/analysis/ideal-laps.json": IdealLaps;
  "generations/{session_key}/{generation}/analysis/lap-times.json": LapTimes;
  "generations/{session_key}/{generation}/analysis/pace-prediction.json": PacePrediction;
  "generations/{session_key}/{generation}/analysis/race-pace.json": RacePace;
  "generations/{session_key}/{generation}/analysis/strategy.json": Strategy;
  "generations/{session_key}/{generation}/analysis/team-mate-comparison.json": TeammateComparison;
  "generations/{session_key}/{generation}/analysis/track-dominance.json": TrackDominance;
  "generations/{session_key}/{generation}/analysis/tyre-degradation.json": TyreDegradation;
  "generations/{session_key}/{generation}/corners.json": Corners;
  "generations/{session_key}/{generation}/coverage.json": Coverage;
  "generations/{session_key}/{generation}/drivers.json": Drivers;
  "generations/{session_key}/{generation}/laps.json": Laps;
  "generations/{session_key}/{generation}/manifest.json": Manifest;
  "generations/{session_key}/{generation}/pit-stops.json": PitStops;
  "generations/{session_key}/{generation}/position-replay.json": PositionReplay;
  "generations/{session_key}/{generation}/race-control.json": RaceControl;
  "generations/{session_key}/{generation}/results.json": Results;
  "generations/{session_key}/{generation}/stints.json": Stints;
  "generations/{session_key}/{generation}/summary.json": SessionSummary;
  "generations/{session_key}/{generation}/telemetry/index.json": TelemetryIndex;
  "generations/{session_key}/{generation}/telemetry/{driver_code}.json": DriverTelemetry;
  "generations/{session_key}/{generation}/weather.json": Weather;
  "index.json": Index;
  "pointers/{session_key}.json": Pointer;
  "standings/{year}.json": Standings;
}
/**
 * analysis/car-performance.json.
 */
export interface CarPerformance {
  caveats: string[];
  drivers: CarPerformanceDriver[];
  teams: CarPerformanceTeam[];
}
/**
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "CarPerformanceDriver".
 */
export interface CarPerformanceDriver {
  /**
   * Per cent, from 0 to 100.
   */
  braking_pct: number | null;
  driver_code: string;
  /**
   * Per cent, from 0 to 100.
   */
  full_throttle_pct: number | null;
  /**
   * Kilometres an hour.
   */
  high_speed_avg_kph: number | null;
  lap_number: number | null;
  /**
   * Kilometres an hour.
   */
  low_speed_avg_kph: number | null;
  /**
   * Kilometres an hour.
   */
  max_speed_kph: number;
  /**
   * Kilometres an hour.
   */
  medium_speed_avg_kph: number | null;
  /**
   * Kilometres an hour.
   */
  p95_speed_kph: number;
  team: string;
}
/**
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "CarPerformanceTeam".
 */
export interface CarPerformanceTeam {
  /**
   * Per cent, from 0 to 100.
   */
  braking_pct: number | null;
  drivers: string[];
  /**
   * Per cent, from 0 to 100.
   */
  full_throttle_pct: number | null;
  /**
   * Kilometres an hour.
   */
  high_speed_avg_kph: number | null;
  /**
   * Kilometres an hour.
   */
  low_speed_avg_kph: number | null;
  /**
   * Kilometres an hour.
   */
  max_speed_kph: number | null;
  /**
   * Kilometres an hour.
   */
  medium_speed_avg_kph: number | null;
  /**
   * Kilometres an hour.
   */
  p95_speed_kph: number | null;
  team: string;
}
/**
 * analysis/corner-analysis.json.
 */
export interface CornerAnalysis {
  caveats: string[];
  corner_source: CornerSource;
  corners: AnalysedCorner[];
  representative_laps: RepresentativeLap[];
}
/**
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "AnalysedCorner".
 */
export interface AnalysedCorner {
  /**
   * The circuit's own number when corner_source is official, otherwise the order found.
   */
  corner_number: number;
  /**
   * Metres.
   */
  distance_m: number | null;
  drivers: CornerDriver[];
  letter: string | null;
  x: number | null;
  y: number | null;
}
/**
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "CornerDriver".
 */
export interface CornerDriver {
  /**
   * Metres.
   */
  apex_distance_m: number;
  /**
   * Kilometres an hour.
   */
  apex_speed_kph: number;
  /**
   * Milliseconds.
   */
  brake_duration_ms: number | null;
  /**
   * False where F1's car feed has no brake reading for part of the approach to the corner, so that where the driver began to brake, or whether they braked at all, is not known. The brake point and the figures counted from it are then null, which is not word that the driver did not brake.
   */
  brake_known: boolean;
  /**
   * Null where the driver did not brake for the corner, and where brake_known is false.
   */
  brake_start_m: number | null;
  /**
   * Metres.
   */
  braking_distance_m: number | null;
  driver_code: string;
  /**
   * Kilometres an hour.
   */
  entry_speed_kph: number | null;
  /**
   * Kilometres an hour.
   */
  exit_speed_kph: number | null;
  /**
   * Kilometres an hour.
   */
  speed_loss_kph: number | null;
}
/**
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "RepresentativeLap".
 */
export interface RepresentativeLap {
  driver_code: string;
  lap_number: number;
  /**
   * Milliseconds.
   */
  lap_time_ms: number | null;
}
/**
 * analysis/ideal-laps.json.
 */
export interface IdealLaps {
  rows: IdealLapRow[];
}
/**
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "IdealLapRow".
 */
export interface IdealLapRow {
  /**
   * Milliseconds.
   */
  best_lap_ms: number | null;
  /**
   * Milliseconds.
   */
  best_sector_1_ms: number | null;
  /**
   * Milliseconds.
   */
  best_sector_2_ms: number | null;
  /**
   * Milliseconds.
   */
  best_sector_3_ms: number | null;
  /**
   * Milliseconds.
   */
  delta_to_ideal_ms: number | null;
  driver_code: string;
  /**
   * Milliseconds.
   */
  ideal_lap_ms: number | null;
}
/**
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "LapTimeSeries".
 */
export interface LapTimeSeries {
  color: string | null;
  /**
   * The driver's code.
   */
  name: string;
  /**
   * Lap numbers.
   */
  x: number[];
  /**
   * Lap times in milliseconds.
   */
  y: number[];
}
/**
 * analysis/pace-prediction.json. Published for practice sessions only: a race has no such file.
 */
export interface PacePrediction {
  available: boolean;
  caveats: string[];
  drivers: PacePredictionDriver[];
  session_type: string;
  teams: PacePredictionTeam[];
}
/**
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "PacePredictionDriver".
 */
export interface PacePredictionDriver {
  compounds: string[];
  confidence: Confidence;
  driver_code: string;
  /**
   * Milliseconds.
   */
  estimated_race_pace_ms: number;
  /**
   * Milliseconds.
   */
  gap_to_best_ms: number | null;
  sample_count: number;
  stint_count: number;
  team: string;
  /**
   * Milliseconds.
   */
  variability_ms: number;
}
/**
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "PacePredictionTeam".
 */
export interface PacePredictionTeam {
  confidence: Confidence;
  drivers: string[];
  /**
   * Milliseconds.
   */
  estimated_race_pace_ms: number;
  /**
   * Milliseconds.
   */
  gap_to_best_ms: number | null;
  sample_count: number;
  team: string;
}
/**
 * analysis/race-pace.json.
 */
export interface RacePace {
  caveats: string[];
  drivers: RacePaceRow[];
  stints: RacePaceRow[];
}
/**
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "RacePaceRow".
 */
export interface RacePaceRow {
  /**
   * The compound most of the laps were on.
   */
  compound: Compound | null;
  driver_code: string;
  /**
   * Milliseconds.
   */
  fastest_clean_lap_ms: number | null;
  /**
   * Milliseconds.
   */
  gap_to_best_ms: number | null;
  lap_count: number;
  /**
   * Milliseconds.
   */
  mean_lap_ms: number | null;
  /**
   * Milliseconds.
   */
  median_lap_ms: number | null;
  /**
   * Null in a row for the whole race.
   */
  stint: number | null;
  /**
   * Milliseconds.
   */
  trimmed_mean_lap_ms: number | null;
}
/**
 * analysis/strategy.json. The stints and stops themselves are in stints.json and pit-stops.json.
 */
export interface Strategy {
  caveats: string[];
  /**
   * Stints by compound. The key UNKNOWN counts stints whose compound F1 did not report.
   */
  compound_usage: {
    [k: string]: number;
  };
  pit_lane_time: PitLaneTime;
  pit_loss: PitLoss;
  /**
   * Milliseconds.
   */
  pit_loss_estimate_ms: number | null;
  undercut_overcut: PaceChangeAcrossStop[];
}
/**
 * Pit-lane transit times from the timing, summarised over the stops F1's pit-stop feed reports.
 *
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "PitLaneTime".
 */
export interface PitLaneTime {
  /**
   * Milliseconds.
   */
  fastest_ms: number | null;
  /**
   * Milliseconds.
   */
  median_ms: number | null;
  /**
   * Milliseconds.
   */
  slowest_ms: number | null;
  /**
   * Every entry to the pit lane, a stop or not.
   */
  stop_count: number;
  /**
   * The stops the three figures are of: the entries to the pit lane that F1's pit-stop feed gives a stationary time for, that have a transit time, and that were not a wait through a red flag.
   */
  timed_stop_count: number;
}
/**
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "PitLoss".
 */
export interface PitLoss {
  baseline_window_laps: number;
  /**
   * Milliseconds.
   */
  estimate_ms: number | null;
  excluded_stop_counts: {
    [k: string]: number;
  };
  minimum_stop_count: number;
  qualifying_stop_count: number;
  /**
   * Milliseconds.
   */
  spread_ms: number | null;
  /**
   * Every entry to the pit lane, a stop or not.
   */
  stop_count: number;
  stops: StopPitLoss[];
}
/**
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "StopPitLoss".
 */
export interface StopPitLoss {
  baseline_lap_count: number;
  /**
   * Milliseconds.
   */
  baseline_lap_ms: number | null;
  driver_code: string | null;
  excluded_reason: PitLossExclusion | null;
  /**
   * Milliseconds.
   */
  in_lap_ms: number | null;
  lap_number: number | null;
  /**
   * Milliseconds.
   */
  out_lap_ms: number | null;
  /**
   * Milliseconds.
   */
  pit_loss_ms: number | null;
}
/**
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "PaceChangeAcrossStop".
 */
export interface PaceChangeAcrossStop {
  /**
   * Milliseconds.
   */
  after_lap_ms: number | null;
  after_lap_number: number | null;
  /**
   * Milliseconds.
   */
  before_lap_ms: number | null;
  before_lap_number: number | null;
  caveat: string;
  driver_code: string;
  /**
   * The lap before the stop minus the lap after it, in milliseconds. Positive is quicker after the stop, which is on other tyres unless the stop list says the tyres were not changed.
   */
  first_clean_lap_gain_ms: number | null;
  /**
   * The lap the driver first came in on, leaving out any entry to the pit lane the car went through without stopping or waited in through a red flag.
   */
  stop_lap: number;
}
/**
 * analysis/team-mate-comparison.json.
 */
export interface TeammateComparison {
  caveats: string[];
  rows: TeammateComparisonRow[];
}
/**
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "TeammateComparisonRow".
 */
export interface TeammateComparisonRow {
  caveat: string | null;
  drivers: TeammateComparisonDriver[];
  /**
   * Milliseconds.
   */
  gap_ms: number | null;
  /**
   * Milliseconds.
   */
  gap_spread_ms: number | null;
  matched_lap_count: number;
  team: string;
  trimmed_lap_count: number;
}
/**
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "TeammateComparisonDriver".
 */
export interface TeammateComparisonDriver {
  /**
   * Milliseconds.
   */
  average_lap_ms: number | null;
  clean_lap_count: number;
  driver_code: string;
  lap_count: number;
}
/**
 * analysis/track-dominance.json.
 */
export interface TrackDominance {
  caveats: string[];
  excluded_drivers: string[];
  minisector_count: number;
  minisectors: Minisector[];
  representative_laps: RepresentativeLap[];
}
/**
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "Minisector".
 */
export interface Minisector {
  /**
   * Milliseconds through the minisector, by driver code.
   */
  driver_times_ms: {
    [k: string]: number;
  };
  /**
   * Metres.
   */
  end_distance_m: number;
  /**
   * Milliseconds.
   */
  gap_to_next_ms: number | null;
  index: number;
  midpoint: Point;
  /**
   * Milliseconds.
   */
  segment_time_ms: number | null;
  /**
   * Metres.
   */
  start_distance_m: number;
  winner_driver_code: string | null;
}
/**
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "Point".
 */
export interface Point {
  x: number | null;
  y: number | null;
}
/**
 * analysis/tyre-degradation.json.
 */
export interface TyreDegradation {
  caveats: string[];
  model: TyreDegradationModel;
  rows: TyreDegradationRow[];
}
/**
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "TyreDegradationModel".
 */
export interface TyreDegradationModel {
  max_slope_relative_standard_error: number;
  /**
   * Milliseconds a lap.
   */
  max_slope_standard_error_ms_per_lap: number;
  method: string;
  minimum_laps: number;
  /**
   * Milliseconds a lap.
   */
  race_fuel_correction_ms_per_lap: number;
  /**
   * Milliseconds a lap.
   */
  sprint_fuel_correction_ms_per_lap: number;
}
/**
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "TyreDegradationRow".
 */
export interface TyreDegradationRow {
  caveats: string[];
  compound: Compound | null;
  /**
   * Null unless fit_status is ok.
   */
  degradation_ms_per_lap: number | null;
  driver_code: string;
  excluded_outlier_count: number;
  fit_status: FitStatus;
  /**
   * Milliseconds a lap.
   */
  fuel_correction_ms_per_lap: number;
  r_squared: number | null;
  /**
   * Milliseconds a lap.
   */
  raw_slope_ms_per_lap: number | null;
  /**
   * Milliseconds.
   */
  residual_spread_ms: number | null;
  /**
   * The stint's clean laps that have a tyre age, which are the ones a fit can use. Those left out of the fit as outliers are still counted here: the fit is of this many less excluded_outlier_count.
   */
  sample_count: number;
  /**
   * Milliseconds a lap.
   */
  slope_standard_error_ms_per_lap: number | null;
  stint: number;
  /**
   * The stint's clean laps, with a tyre age or without. F1 gives no age for a set that went on used.
   */
  stint_length: number;
}
/**
 * corners.json: the circuit's official corner positions. Empty when none were archived.
 */
export interface Corners {
  corners: Corner[];
  /**
   * Null when no corner has a distance.
   */
  distance_source: DistanceSource | null;
  /**
   * False when the corner positions do not lie on the line reference_lap drove: the archived map is not of this track, or no lap of the session has position data that is whole. They should not be drawn over this session's position data, and the corner analysis infers its corners instead. Null when there is no lap to check against.
   */
  fits_track: boolean | null;
  /**
   * Metres from the track, as reference_lap drove it, of the corner furthest from it. Null when there is no lap to check against.
   */
  off_track_m: number | null;
  /**
   * The lap the corners were checked against, and placed along when distance_source is telemetry: the fastest clean lap whose position data is whole, or failing that the fastest that has any. Null when no lap has any.
   */
  reference_lap: ReferenceLap | null;
  /**
   * Degrees to turn the position data by so the map sits as F1 draws it.
   */
  rotation: number | null;
}
/**
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "Corner".
 */
export interface Corner {
  /**
   * Degrees. Which way to draw the corner's label from its position.
   */
  angle: number | null;
  /**
   * Metres from the start line. Null when the corner could not be placed along the lap.
   */
  distance_m: number | null;
  /**
   * Set where one number covers several corners, such as 1A.
   */
  letter: string | null;
  number: number;
  /**
   * In the units of the position data, tenths of a metre.
   */
  x: number;
  y: number;
}
/**
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "ReferenceLap".
 */
export interface ReferenceLap {
  driver_code: string;
  lap_number: number;
  /**
   * The lap's length as its own telemetry measures it, in metres.
   */
  length_m: number;
}
/**
 * coverage.json: what arrived for this session, and what it is short of.
 */
export interface Coverage {
  circuit_corners: number;
  /**
   * True when shortfalls is empty.
   */
  complete: boolean;
  drivers: DriverCoverage[];
  feeds: CoverageFeeds;
  /**
   * The longest hole between two samples that a lap's car or position data may have and still count.
   */
  max_sample_gap_seconds: number;
  /**
   * Stops F1's pit-stop feed gives a stationary time or a pit-lane time for.
   */
  pit_stops_in_series: number;
  /**
   * Entries to the pit lane the timing shows, whether or not the car stopped: a wait through a red flag and a drive-through penalty are each one.
   */
  pit_stops_in_timing: number;
  session_ended: boolean;
  shortfalls: Shortfall[];
  /**
   * The race distance in laps.
   */
  total_laps: number | null;
}
/**
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "DriverCoverage".
 */
export interface DriverCoverage {
  /**
   * Timed laps whose car data runs from start to end with no long hole.
   */
  car_laps: number;
  /**
   * Laps in the classification. Null when there is none.
   */
  classified_laps: number | null;
  driver_code: string;
  /**
   * Laps FastF1 added for a retirement. They are in laps.json and were never timed.
   */
  generated_laps: number;
  in_driver_list: boolean;
  number: string;
  /**
   * The same for position data.
   */
  position_laps: number;
  /**
   * Laps F1 timed.
   */
  timing_laps: number;
  /**
   * Timed laps with a tyre age as well.
   */
  tyre_age_laps: number;
  /**
   * Timed laps with a compound and a stint.
   */
  tyre_laps: number;
}
/**
 * Whether each feed arrived at all.
 *
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "CoverageFeeds".
 */
export interface CoverageFeeds {
  car_data: boolean;
  circuit_info: boolean;
  lap_count: boolean;
  pit_stop_series: boolean;
  position: boolean;
  race_control: boolean;
  session_info: boolean;
  session_status: boolean;
  timing_data: boolean;
  track_status: boolean;
  weather: boolean;
}
/**
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "Shortfall".
 */
export interface Shortfall {
  bar: CoverageBar;
  detail: string;
  /**
   * The driver's code, or null when the whole session is short.
   */
  driver: string | null;
}
/**
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "Driver".
 */
export interface Driver {
  /**
   * The code that names the driver in every other artifact: F1's three letters, or the car number as text for a driver neither F1's driver list nor the classification names.
   */
  code: string;
  /**
   * F1's country code for the driver. F1 left it empty throughout 2026.
   */
  country: string | null;
  /**
   * The driver's code in lower case.
   */
  driver_id: string;
  full_name: string;
  /**
   * The racing number.
   */
  number: number | null;
  /**
   * Null when F1's driver list names no team.
   */
  team: Team | null;
}
/**
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "Team".
 */
export interface Team {
  /**
   * The team's colour as #RRGGBB.
   */
  color: string | null;
  name: string;
  /**
   * The team's name in lower case with hyphens.
   */
  team_id: string;
}
/**
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "Lap".
 */
export interface Lap {
  /**
   * Null where F1 reported none.
   */
  compound: Compound | null;
  driver_code: string;
  /**
   * FastF1's judgement that the lap's timing is whole and consistent.
   */
  is_accurate: boolean;
  /**
   * The lap time was deleted by the stewards.
   */
  is_deleted: boolean;
  is_pit_in_lap: boolean;
  is_pit_out_lap: boolean;
  lap_number: number;
  /**
   * Milliseconds. Null for a lap F1 did not time.
   */
  lap_time_ms: number | null;
  /**
   * Position at the end of the lap.
   */
  position: number | null;
  /**
   * Milliseconds.
   */
  sector_1_ms: number | null;
  /**
   * Milliseconds.
   */
  sector_2_ms: number | null;
  /**
   * Milliseconds.
   */
  sector_3_ms: number | null;
  /**
   * Which of the driver's sets of tyres the lap was run on, counted as F1 counts them but for one thing: F1 gives a new number to a car that went through the pit lane and kept its tyres, and such a lap keeps the number of the set it is still on.
   */
  stint: number | null;
  /**
   * Every track status code seen during the lap, run together: 1 clear, 2 yellow, 4 safety car, 5 red flag, 6 virtual safety car, 7 virtual safety car ending.
   */
  track_status: string | null;
  /**
   * Laps the set had done at the end of this lap. Null for a set that went on used: F1 does not report its age.
   */
  tyre_age: number | null;
}
/**
 * manifest.json: every file of a generation. Its SHA-256 is the generation's name.
 */
export interface Manifest {
  files: ManifestFile[];
  format_version: number;
  identity: Identity;
  pipeline_version: number;
  session_key: number;
}
/**
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "ManifestFile".
 */
export interface ManifestFile {
  path: string;
  sha256: string;
  size_bytes: number;
}
/**
 * Who a session is, from F1's own session information (f1data/identity.py). Two fields are the calendar's, as it stood when the session was fetched: the start time and the round.
 *
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "Identity".
 */
export interface Identity {
  archive_path: string;
  circuit_key: number | null;
  circuit_name: string | null;
  country: string | null;
  location: string | null;
  meeting_key: number;
  meeting_name: string;
  meeting_official_name: string | null;
  /**
   * The round when the session was fetched. The index has the round as it is now.
   */
  round_at_fetch: number | null;
  session_key: number;
  session_name: string;
  session_type: SessionType;
  /**
   * When the calendar said the session starts.
   */
  start_time_utc: string;
  year: number;
}
/**
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "PitStop".
 */
export interface PitStop {
  driver_code: string;
  /**
   * Milliseconds from pit entry to pit exit, from the timing. Null when the car did not come back out.
   */
  duration_ms: number | null;
  /**
   * When the car crossed the pit entry, in milliseconds on the session clock. Null for a stop only F1's pit-stop feed reports.
   */
  entry_time_ms: number | null;
  /**
   * The lap the car came in on.
   */
  lap_number: number;
  /**
   * Milliseconds in the pit lane, from F1's pit-stop feed.
   */
  pit_lane_ms: number | null;
  sources: PitStopSources;
  /**
   * Milliseconds the car stood still, from F1's pit-stop feed.
   */
  stationary_ms: number | null;
  /**
   * Whether the car went out on another set of tyres than it came in on, by F1's tyre data. False for a car that kept its tyres: a drive-through penalty, a penalty served in the pit box, a passage behind the safety car. Null where the tyre data does not say: it names no compound for the lap the car came in on or the one after, or the car did not go out again. The tyre data can lag a stop by some laps, so false beside a stationary time is still a stop.
   */
  tyres_changed: boolean | null;
  /**
   * Whether the session was red-flagged while the car was in the pit lane. The duration is then a wait for the restart and not a pit stop, and the strategy analysis leaves it out of its pit-lane figures.
   */
  under_red_flag: boolean;
}
/**
 * Where each figure of a pit stop comes from. Null beside a figure that is null.
 *
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "PitStopSources".
 */
export interface PitStopSources {
  /**
   * timing: the gap between the timing's pit-entry and pit-exit times.
   */
  duration_ms: "timing" | null;
  /**
   * pit_stop_series: F1's own pit-stop feed.
   */
  pit_lane_ms: "pit_stop_series" | null;
  /**
   * pit_stop_series: F1's own pit-stop feed.
   */
  stationary_ms: "pit_stop_series" | null;
}
/**
 * position-replay.json: where every car was, every few seconds.
 */
export interface PositionReplay {
  drivers: ReplayDriver[];
  /**
   * The length of a frame's window in milliseconds.
   */
  interval_ms: number;
  /**
   * The lap the session had reached: the highest any car had started.
   */
  lap_number: (number | null)[];
  /**
   * The start of each frame's window, in milliseconds on the session clock.
   */
  time_ms: number[];
}
/**
 * One car's track, one entry per frame. Null in a frame the car has no position for.
 *
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "ReplayDriver".
 */
export interface ReplayDriver {
  /**
   * Metres into the car's current lap. Null as well in a frame where the car has a position and no car data.
   */
  distance_m: (number | null)[];
  driver_code: string;
  /**
   * Null as well in a frame where the car has a position and no car data.
   */
  speed_kph: (number | null)[];
  /**
   * Tenths of a metre.
   */
  x: (number | null)[];
  y: (number | null)[];
}
/**
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "RaceControlMessage".
 */
export interface RaceControlMessage {
  category: string;
  flag: string | null;
  lap_number: number | null;
  message: string;
  scope: string | null;
  /**
   * Milliseconds on the session clock.
   */
  time_ms: number | null;
}
/**
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "Result".
 */
export interface Result {
  /**
   * For a driver with laps_down: milliseconds after the winner that they took the flag. Not a gap, since they had fewer laps to run: it only orders the cars on one lap.
   */
  behind_at_flag_ms: number | null;
  /**
   * The position as the classification prints it: a number, or a letter such as R for retired.
   */
  classified_position: string | null;
  driver_code: string;
  /**
   * Milliseconds behind the winner, for a driver who finished on the same lap. Null for everyone else.
   */
  gap_ms: number | null;
  /**
   * Starting position. 0 for a start from the pit lane.
   */
  grid: number | null;
  /**
   * Laps completed. Null for a driver the classification leaves out.
   */
  laps: number | null;
  /**
   * Laps behind the winner, for a driver who took the flag one or more down. Null for one who did not finish, classified or not. Null for everyone else.
   */
  laps_down: number | null;
  points: number | null;
  /**
   * Null for a driver who took part and whom the classification leaves out. Such rows come last.
   */
  position: number | null;
  /**
   * True when Jolpica has no classification for the session. The rows are then the order on track from the timing alone, with no status, points or grid.
   */
  provisional: boolean;
  status: string | null;
  /**
   * The winner's race time in milliseconds. Null for everyone else.
   */
  time_ms: number | null;
}
/**
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "Stint".
 */
export interface Stint {
  compound: Compound | null;
  driver_code: string;
  end_lap: number;
  lap_count: number;
  start_lap: number;
  stint: number | null;
}
/**
 * summary.json: what the session is, in F1's own words.
 */
export interface SessionSummary {
  /**
   * F1's short name for the circuit.
   */
  circuit: string | null;
  /**
   * When the session clock read zero, in UTC to the millisecond. Every position in time in this generation is milliseconds after it.
   */
  clock_zero_utc: string | null;
  country: string | null;
  driver_count: number;
  /**
   * True only for the invented session used in local development.
   */
  is_sample: boolean;
  /**
   * Laps in laps.json, over every driver. That counts the lap a car stopped on, which FastF1 adds a row for and F1's timing has none of: one or two in most races.
   */
  lap_count: number;
  /**
   * The meeting's name as F1's session information gives it.
   */
  meeting: string;
  /**
   * The session's name, such as Race or Sprint.
   */
  session: string;
  /**
   * F1's key for the session. It names the session everywhere.
   */
  session_key: number;
  session_type: SessionType;
  /**
   * One line for a heading: the air and track temperature ranges, and rain or dry.
   */
  weather_summary: string;
  year: number;
}
/**
 * telemetry/index.json: which laps have telemetry, and where.
 */
export interface TelemetryIndex {
  /**
   * The arrays a lap carries. DRS is absent when it never changes in the session, as in 2026, which has no DRS.
   */
  channels: TelemetryChannel[];
  drivers: TelemetryDriverEntry[];
  /**
   * A lap with more samples is thinned evenly to this many, keeping both ends.
   */
  max_samples_per_lap: number;
}
/**
 * One driver's laps that have telemetry, as parallel arrays with one entry per lap.
 *
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "TelemetryDriverEntry".
 */
export interface TelemetryDriverEntry {
  compound: (Compound | null)[];
  driver_code: string;
  /**
   * False for a lap with no usable position data, and so no x and y.
   */
  has_position: boolean[];
  /**
   * Each lap's four flags as in laps.json, so that a page can offer a clean lap first: one that is timed accurately, was not deleted, and neither enters nor leaves the pits.
   */
  is_accurate: (boolean | null)[];
  is_deleted: (boolean | null)[];
  is_pit_in_lap: (boolean | null)[];
  is_pit_out_lap: (boolean | null)[];
  lap_number: number[];
  /**
   * Each lap's time as in laps.json, so that a lap can be picked from here alone.
   */
  lap_time_ms: (number | null)[];
  /**
   * The driver's file, relative to the generation.
   */
  path: string;
  /**
   * Samples each lap has at full resolution, which is what the analyses read.
   */
  raw_sample_count: number[];
  /**
   * Samples published for each lap.
   */
  sample_count: number[];
}
/**
 * telemetry/<driver_code>.json: every lap of one driver that has car data from end to end.
 */
export interface DriverTelemetry {
  driver_code: string;
  laps: TelemetryLap[];
}
/**
 * One lap as parallel arrays, one entry per sample.
 *
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "TelemetryLap".
 */
export interface TelemetryLap {
  /**
   * Whether the brake was on. Null from a sample F1's car feed gave no reading of the brake for (it sends 104) until the next that has one. FastF1 reads that mark as the brake on, so it is taken from F1's raw feed.
   */
  brake: (boolean | null)[];
  /**
   * Metres since the lap started, integrated from speed.
   */
  distance_m: number[];
  /**
   * F1's DRS code. Null when the channel is left out of the session.
   */
  drs: number[] | null;
  /**
   * 0 for neutral, 1 to 8. Null from a sample for which F1's car feed sent a number that is no gear until the next that is one.
   */
  gear: (number | null)[];
  lap_number: number;
  rpm: number[];
  /**
   * Kilometres an hour.
   */
  speed_kph: number[];
  /**
   * When the lap started, in milliseconds on the session clock.
   */
  start_ms: number;
  /**
   * 0 to 100. Null at a sample F1's car feed gave no reading of the throttle for (it sends 104, most often for both pedals at once while it repeats the speed it last had), and between such a sample and the one before or after.
   */
  throttle_pct: (number | null)[];
  /**
   * Milliseconds since the lap started. Add start_ms for the session clock.
   */
  time_ms: number[];
  /**
   * Tenths of a metre. Null when the lap has no usable position data. Within a lap that has, null for a sample taken before the position feed started or after it stopped, which can only be within a few seconds of either end of the lap.
   */
  x: (number | null)[] | null;
  y: (number | null)[] | null;
}
/**
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "WeatherSample".
 */
export interface WeatherSample {
  /**
   * Degrees Celsius. Null, like the track temperature and the humidity, when F1's feed gave no value for it, or gave the zero it sends for a sensor with no reading: exactly 0 between readings twenty or more from it.
   */
  air_temp_c: number | null;
  /**
   * Per cent, from 0 to 100.
   */
  humidity_pct: number | null;
  /**
   * In a race or sprint, the lap the leader was on. Null before the start, after the flag, and in any other session.
   */
  lap_number: number | null;
  /**
   * Null, like any other reading of a sample, when F1's feed gave no value for it.
   */
  rainfall: boolean | null;
  /**
   * Milliseconds on the session clock.
   */
  time_ms: number;
  /**
   * Degrees Celsius.
   */
  track_temp_c: number | null;
  /**
   * Kilometres an hour. F1 reports metres a second.
   */
  wind_speed_kph: number | null;
}
/**
 * index.json: the calendar as it is now, with each published session attached.
 */
export interface Index {
  format_version: number;
  schema_version: number;
  seasons: IndexSeason[];
  unscheduled: UnscheduledSession[];
}
/**
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "IndexSeason".
 */
export interface IndexSeason {
  meetings: IndexMeeting[];
  year: number;
}
/**
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "IndexMeeting".
 */
export interface IndexMeeting {
  /**
   * F1's key for the circuit, from the same source.
   */
  circuit_key: number | null;
  circuit_name: string | null;
  country: string | null;
  date: string | null;
  format: string | null;
  location: string | null;
  /**
   * F1's key for the meeting, which does not move. Known once a session of the meeting is published.
   */
  meeting_key: number | null;
  name: string;
  official_name: string | null;
  /**
   * As the calendar has it now. It moves when the calendar changes.
   */
  round: number;
  sessions: IndexSession[];
}
/**
 * A session of the calendar. The last two keys are there only once it is published.
 *
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "IndexSession".
 */
export interface IndexSession {
  complete?: boolean;
  in_scope: boolean;
  name: string;
  session_key?: number;
  /**
   * UTC, as ISO 8601.
   */
  start_time_utc: string | null;
  type: SessionType;
}
/**
 * A published session the calendar no longer lists.
 *
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "UnscheduledSession".
 */
export interface UnscheduledSession {
  complete: boolean;
  meeting_name: string;
  name: string;
  session_key: number;
  /**
   * UTC, as ISO 8601.
   */
  start_time_utc: string;
  type: SessionType;
  year: number;
}
/**
 * pointers/<session_key>.json: which generation is the published one.
 */
export interface Pointer {
  /**
   * What else the generation was built from, outside the archive and the classification: under calendar, the calendar entry the session was built as (year, round, names, and a checksum of the whole row). The publisher's own record, by which it knows to build again; a reader takes the round from the index.
   */
  also: {} | null;
  classification_fingerprint: string | null;
  coverage: PointerCoverage;
  format_version: number;
  generation: string;
  identity: Identity;
  manifest: ManifestReference;
  pipeline_version: number;
  previous_generation: string | null;
  published_at: string;
  /**
   * A checksum of what the snapshot's record said of its feeds when the session was judged. A record corrected afterwards has the session decided again.
   */
  record: string | null;
  schema_version: number;
  session_key: number;
  snapshot_id: string;
}
/**
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "PointerCoverage".
 */
export interface PointerCoverage {
  complete: boolean;
  shortfalls: Shortfall[];
}
/**
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "ManifestReference".
 */
export interface ManifestReference {
  sha256: string;
  size_bytes: number;
}
/**
 * standings/<year>.json: the championship tables as Jolpica has them.
 */
export interface Standings {
  constructors: ConstructorStanding[];
  drivers: DriverStanding[];
  format_version: number;
  rounds: StandingsRounds;
  schema_version: number;
  year: number;
}
/**
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "ConstructorStanding".
 */
export interface ConstructorStanding {
  constructor_id: string | null;
  name: string | null;
  points: number | null;
  position: number | null;
  wins: number | null;
}
/**
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "DriverStanding".
 */
export interface DriverStanding {
  constructors: string[];
  driver_code: string | null;
  driver_number: number | null;
  family_name: string | null;
  given_name: string | null;
  points: number | null;
  position: number | null;
  wins: number | null;
}
/**
 * The round each table stands after.
 */
export interface StandingsRounds {
  constructors: number;
  drivers: number;
}
/**
 * analysis/car-performance.json.
 *
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "CarPerformance".
 */
export interface CarPerformance1 {
  caveats: string[];
  drivers: CarPerformanceDriver[];
  teams: CarPerformanceTeam[];
}
/**
 * analysis/corner-analysis.json.
 *
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "CornerAnalysis".
 */
export interface CornerAnalysis1 {
  caveats: string[];
  corner_source: CornerSource;
  corners: AnalysedCorner[];
  representative_laps: RepresentativeLap[];
}
/**
 * corners.json: the circuit's official corner positions. Empty when none were archived.
 *
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "Corners".
 */
export interface Corners1 {
  corners: Corner[];
  /**
   * Null when no corner has a distance.
   */
  distance_source: DistanceSource | null;
  /**
   * False when the corner positions do not lie on the line reference_lap drove: the archived map is not of this track, or no lap of the session has position data that is whole. They should not be drawn over this session's position data, and the corner analysis infers its corners instead. Null when there is no lap to check against.
   */
  fits_track: boolean | null;
  /**
   * Metres from the track, as reference_lap drove it, of the corner furthest from it. Null when there is no lap to check against.
   */
  off_track_m: number | null;
  /**
   * The lap the corners were checked against, and placed along when distance_source is telemetry: the fastest clean lap whose position data is whole, or failing that the fastest that has any. Null when no lap has any.
   */
  reference_lap: ReferenceLap | null;
  /**
   * Degrees to turn the position data by so the map sits as F1 draws it.
   */
  rotation: number | null;
}
/**
 * coverage.json: what arrived for this session, and what it is short of.
 *
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "Coverage".
 */
export interface Coverage1 {
  circuit_corners: number;
  /**
   * True when shortfalls is empty.
   */
  complete: boolean;
  drivers: DriverCoverage[];
  feeds: CoverageFeeds;
  /**
   * The longest hole between two samples that a lap's car or position data may have and still count.
   */
  max_sample_gap_seconds: number;
  /**
   * Stops F1's pit-stop feed gives a stationary time or a pit-lane time for.
   */
  pit_stops_in_series: number;
  /**
   * Entries to the pit lane the timing shows, whether or not the car stopped: a wait through a red flag and a drive-through penalty are each one.
   */
  pit_stops_in_timing: number;
  session_ended: boolean;
  shortfalls: Shortfall[];
  /**
   * The race distance in laps.
   */
  total_laps: number | null;
}
/**
 * telemetry/<driver_code>.json: every lap of one driver that has car data from end to end. A lap with a hole of more than a few seconds in its car data is not here (max_sample_gap_seconds in coverage.json), and the coverage counts it as missing.
 *
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "DriverTelemetry".
 */
export interface DriverTelemetry1 {
  driver_code: string;
  laps: TelemetryLap[];
}
/**
 * analysis/ideal-laps.json.
 *
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "IdealLaps".
 */
export interface IdealLaps1 {
  rows: IdealLapRow[];
}
/**
 * index.json: the calendar as it is now, with each published session attached.
 *
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "Index".
 */
export interface Index1 {
  format_version: number;
  schema_version: number;
  seasons: IndexSeason[];
  unscheduled: UnscheduledSession[];
}
/**
 * manifest.json: every file of a generation. Its SHA-256 is the generation's name.
 *
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "Manifest".
 */
export interface Manifest1 {
  files: ManifestFile[];
  format_version: number;
  identity: Identity;
  pipeline_version: number;
  session_key: number;
}
/**
 * analysis/pace-prediction.json. Published for practice sessions only: a race has no such file.
 *
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "PacePrediction".
 */
export interface PacePrediction1 {
  available: boolean;
  caveats: string[];
  drivers: PacePredictionDriver[];
  session_type: string;
  teams: PacePredictionTeam[];
}
/**
 * pointers/<session_key>.json: which generation is the published one.
 *
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "Pointer".
 */
export interface Pointer1 {
  /**
   * What else the generation was built from, outside the archive and the classification: under calendar, the calendar entry the session was built as (year, round, names, and a checksum of the whole row). The publisher's own record, by which it knows to build again; a reader takes the round from the index.
   */
  also: {} | null;
  classification_fingerprint: string | null;
  coverage: PointerCoverage;
  format_version: number;
  generation: string;
  identity: Identity;
  manifest: ManifestReference;
  pipeline_version: number;
  previous_generation: string | null;
  published_at: string;
  /**
   * A checksum of what the snapshot's record said of its feeds when the session was judged. A record corrected afterwards has the session decided again.
   */
  record: string | null;
  schema_version: number;
  session_key: number;
  snapshot_id: string;
}
/**
 * position-replay.json: where every car was, every few seconds. Empty arrays when the session has no position data. A session whose position feed stops part-way has frames up to where it stops.
 *
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "PositionReplay".
 */
export interface PositionReplay1 {
  drivers: ReplayDriver[];
  /**
   * The length of a frame's window in milliseconds.
   */
  interval_ms: number;
  /**
   * The lap the session had reached: the highest any car had started.
   */
  lap_number: (number | null)[];
  /**
   * The start of each frame's window, in milliseconds on the session clock.
   */
  time_ms: number[];
}
/**
 * analysis/race-pace.json.
 *
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "RacePace".
 */
export interface RacePace1 {
  caveats: string[];
  drivers: RacePaceRow[];
  stints: RacePaceRow[];
}
/**
 * summary.json: what the session is, in F1's own words.
 *
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "SessionSummary".
 */
export interface SessionSummary1 {
  /**
   * F1's short name for the circuit.
   */
  circuit: string | null;
  /**
   * When the session clock read zero, in UTC to the millisecond. Every position in time in this generation is milliseconds after it.
   */
  clock_zero_utc: string | null;
  country: string | null;
  driver_count: number;
  /**
   * True only for the invented session used in local development.
   */
  is_sample: boolean;
  /**
   * Laps in laps.json, over every driver. That counts the lap a car stopped on, which FastF1 adds a row for and F1's timing has none of: one or two in most races.
   */
  lap_count: number;
  /**
   * The meeting's name as F1's session information gives it.
   */
  meeting: string;
  /**
   * The session's name, such as Race or Sprint.
   */
  session: string;
  /**
   * F1's key for the session. It names the session everywhere.
   */
  session_key: number;
  session_type: SessionType;
  /**
   * One line for a heading: the air and track temperature ranges, and rain or dry.
   */
  weather_summary: string;
  year: number;
}
/**
 * standings/<year>.json: the championship tables as Jolpica has them.
 *
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "Standings".
 */
export interface Standings1 {
  constructors: ConstructorStanding[];
  drivers: DriverStanding[];
  format_version: number;
  rounds: StandingsRounds;
  schema_version: number;
  year: number;
}
/**
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "StandingsRounds".
 */
export interface StandingsRounds1 {
  constructors: number;
  drivers: number;
}
/**
 * analysis/strategy.json. The stints and stops themselves are in stints.json and pit-stops.json.
 *
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "Strategy".
 */
export interface Strategy1 {
  caveats: string[];
  /**
   * Stints by compound. The key UNKNOWN counts stints whose compound F1 did not report.
   */
  compound_usage: {
    [k: string]: number;
  };
  pit_lane_time: PitLaneTime;
  pit_loss: PitLoss;
  /**
   * Milliseconds.
   */
  pit_loss_estimate_ms: number | null;
  undercut_overcut: PaceChangeAcrossStop[];
}
/**
 * analysis/team-mate-comparison.json.
 *
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "TeammateComparison".
 */
export interface TeammateComparison1 {
  caveats: string[];
  rows: TeammateComparisonRow[];
}
/**
 * telemetry/index.json: which laps have telemetry, and where.
 *
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "TelemetryIndex".
 */
export interface TelemetryIndex1 {
  /**
   * The arrays a lap carries. DRS is absent when it never changes in the session, as in 2026, which has no DRS.
   */
  channels: TelemetryChannel[];
  drivers: TelemetryDriverEntry[];
  /**
   * A lap with more samples is thinned evenly to this many, keeping both ends.
   */
  max_samples_per_lap: number;
}
/**
 * analysis/track-dominance.json.
 *
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "TrackDominance".
 */
export interface TrackDominance1 {
  caveats: string[];
  excluded_drivers: string[];
  minisector_count: number;
  minisectors: Minisector[];
  representative_laps: RepresentativeLap[];
}
/**
 * analysis/tyre-degradation.json.
 *
 * This interface was referenced by `Formula1DataPublishedFormat2`'s JSON-Schema
 * via the `definition` "TyreDegradation".
 */
export interface TyreDegradation1 {
  caveats: string[];
  model: TyreDegradationModel;
  rows: TyreDegradationRow[];
}
