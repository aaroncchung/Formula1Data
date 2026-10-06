export type Team = {
  team_id: string;
  name: string;
  color?: string | null;
};

export type Driver = {
  driver_id: string;
  code: string;
  full_name: string;
  number?: number | null;
  team: Team;
  country?: string | null;
};

export type Season = {
  year: number;
  meeting_count: number;
  ingested_meeting_count: number;
  is_sample: boolean;
};

export type Circuit = {
  circuit_id: string;
  name: string;
  country: string;
  location?: string | null;
  latitude?: number | null;
  longitude?: number | null;
};

export type Meeting = {
  meeting_id: string;
  year: number;
  round: number;
  name: string;
  official_name?: string | null;
  circuit: Circuit;
  start_date?: string | null;
  country: string;
  sessions_available: string[];
  is_ingested: boolean;
  is_sample: boolean;
};

export type Session = {
  session_id: string;
  year: number;
  round: number;
  meeting_id: string;
  name: string;
  type: string;
  start_time?: string | null;
  end_time?: string | null;
  status: "available" | "missing" | "sample";
  is_sample: boolean;
};

export type SessionSummary = {
  session_id: string;
  meeting: string;
  session: string;
  year: number;
  round: number;
  circuit: string;
  country: string;
  driver_count: number;
  lap_count: number;
  weather_summary: string;
  is_sample: boolean;
  available_sections: string[];
};

export type Lap = {
  session_id: string;
  driver_code: string;
  lap_number: number;
  lap_time_ms?: number | null;
  sector_1_ms?: number | null;
  sector_2_ms?: number | null;
  sector_3_ms?: number | null;
  compound?: string | null;
  tyre_age?: number | null;
  stint?: number | null;
  position?: number | null;
  is_pit_in_lap: boolean;
  is_pit_out_lap: boolean;
  is_deleted: boolean;
  is_accurate: boolean;
  track_status?: string | null;
};

export type Stint = {
  session_id: string;
  driver_code: string;
  stint: number;
  compound: string;
  start_lap: number;
  end_lap: number;
  lap_count: number;
};

export type PitStop = {
  session_id: string;
  driver_code: string;
  lap_number: number;
  /** Pit-lane transit, entry to exit. Not the stationary time and not pit loss. */
  duration_ms?: number | null;
  /**
   * When the car entered the pit lane, on the session clock, as pandas prints
   * a duration (`0 days 01:22:52.191000`). Not a time of day, whatever the
   * name says; read it with lib/pandas-time.ts.
   */
  local_time?: string | null;
};

export type WeatherSample = {
  session_id: string;
  /** Null in every sample published so far, so nothing may be plotted against it. */
  lap_number?: number | null;
  /** The session clock as a pandas duration; read it with lib/pandas-time.ts. */
  timestamp?: string | null;
  air_temp_c?: number | null;
  track_temp_c?: number | null;
  humidity_pct?: number | null;
  rainfall: boolean;
  wind_speed_kph?: number | null;
};

export type RaceControlMessage = {
  session_id: string;
  lap_number?: number | null;
  /** A UTC date and time as pandas prints one, `2026-06-28 12:20:00`, with no zone. */
  timestamp?: string | null;
  category: string;
  message: string;
  flag?: string | null;
  scope?: string | null;
};

export type Result = {
  session_id: string;
  position: number;
  driver_code: string;
  classified_position?: string | null;
  status?: string | null;
  points?: number | null;
  grid?: number | null;
  /**
   * A pandas duration that is the winner's race time, a gap, or for a lapped
   * driver neither; lib/results-view.ts turns it into what a table shows.
   */
  gap?: string | null;
  laps?: number | null;
};

export type ChartSeries = {
  name: string;
  x: Array<string | number>;
  y: Array<string | number | null>;
  color?: string | null;
  metadata: Record<string, unknown>;
};

export type RacePaceRow = {
  driver_code: string;
  median_lap_ms?: number | null;
  mean_lap_ms?: number | null;
  trimmed_mean_lap_ms?: number | null;
  fastest_clean_lap_ms?: number | null;
  lap_count: number;
  compound?: string | null;
  stint?: number | null;
  gap_to_best_ms?: number | null;
};

export type RacePaceResult = {
  session_id: string;
  drivers: RacePaceRow[];
  stints: RacePaceRow[];
  caveats: string[];
};

/**
 * One stint's degradation fit (`calculate_fuel_adjusted_tyre_degradation` in
 * backend/app/analysis/advanced.py).
 *
 * The fields marked "pipeline 2" are absent from a generation built before
 * the analysis methods were fixed, which reported a rate for any three laps.
 * Read a row through `tyreFit` in lib/tyre-chart.ts, which decides whether it
 * holds a rate at all.
 */
export type TyreDegradationRow = {
  driver_code: string;
  compound: string;
  stint: number;
  /** The fuel-adjusted rate. Null when the fit is not reported. */
  degradation_ms_per_lap?: number | null;
  r_squared?: number | null;
  sample_count: number;
  stint_length: number;
  caveats: string[];
  /** The fitted slope before the fuel correction. Null when the fit is not reported. */
  raw_slope_ms_per_lap?: number | null;
  fuel_correction_ms_per_lap?: number | null;
  excluded_outlier_count?: number | null;
  /** Pipeline 2. Scatter of the laps about the fitted line. */
  residual_spread_ms?: number | null;
  /** Pipeline 2. What decides whether a rate is reported. */
  slope_standard_error_ms_per_lap?: number | null;
  /** Pipeline 2: `ok`, `poor_fit` or `too_few_laps`. Only `ok` comes with a rate. */
  fit_status?: string | null;
};

export type TyreDegradationResult = {
  session_id: string;
  rows: TyreDegradationRow[];
  caveats?: string[];
};

export type TelemetryComparison = {
  session_id: string;
  driver_a: { driver_code: string; team?: string | null; lap_time_ms?: number | null; compound?: string | null; session?: string | null; lap_number: number };
  driver_b: { driver_code: string; team?: string | null; lap_time_ms?: number | null; compound?: string | null; session?: string | null; lap_number: number };
  distance_m: number[];
  speed_a: Array<number | null>;
  speed_b: Array<number | null>;
  throttle_a: Array<number | null>;
  throttle_b: Array<number | null>;
  brake_a: Array<number | null>;
  brake_b: Array<number | null>;
  rpm_a: Array<number | null>;
  rpm_b: Array<number | null>;
  gear_a: Array<number | null>;
  gear_b: Array<number | null>;
  drs_a: Array<number | null>;
  drs_b: Array<number | null>;
  delta_speed_kph: Array<number | null>;
  delta_time_ms?: Array<number | null>;
  track_x?: Array<number | null>;
  track_y?: Array<number | null>;
  caveats: string[];
};

export type IdealLapRow = {
  driver_code: string;
  best_sector_1_ms?: number | null;
  best_sector_2_ms?: number | null;
  best_sector_3_ms?: number | null;
  ideal_lap_ms?: number | null;
  best_lap_ms?: number | null;
  delta_to_ideal_ms?: number | null;
};

export type IdealLapsResult = {
  session_id: string;
  rows: IdealLapRow[];
};

export type TeammateComparisonDriver = {
  driver_code: string;
  /**
   * From pipeline 2 this and `lap_count` are over the laps both team-mates ran
   * cleanly and that were kept after trimming, so the gap is the difference
   * between the two averages. Before, they were over the driver's own laps.
   */
  average_lap_ms?: number | null;
  lap_count: number;
  /** Pipeline 2. Every clean lap the driver ran, matched or not. */
  clean_lap_count?: number;
};

/** One team (`calculate_teammate_comparison` in backend/app/analysis/teammate_comparison.py). */
export type TeammateComparisonRow = {
  team: string;
  /** The quicker driver first, so the gap is never negative. */
  drivers: TeammateComparisonDriver[];
  /** Null from pipeline 2 when too few laps match; `caveat` then says how many did. */
  gap_ms?: number | null;
  /** Pipeline 2. Lap-to-lap spread of the matched differences. */
  gap_spread_ms?: number | null;
  /** Pipeline 2. Laps both drivers ran cleanly. */
  matched_lap_count?: number;
  /** Pipeline 2. Matched laps dropped as the most extreme differences. */
  trimmed_lap_count?: number;
  caveat?: string | null;
};

export type TeammateComparisonResult = {
  session_id: string;
  rows: TeammateComparisonRow[];
  caveats: string[];
};

/**
 * The change in pace across a driver's first stop.
 *
 * `first_clean_lap_gain_ms` is the lap before minus the lap after, so a
 * POSITIVE value means the driver was quicker on the new tyres. Read it
 * through `paceChange` in lib/strategy-view.ts.
 */
export type StrategyEstimate = {
  driver_code: string;
  stop_lap: number;
  first_clean_lap_gain_ms?: number | null;
  /** Pipeline 2: the two laps compared. Null when there is no such lap. */
  before_lap_number?: number | null;
  before_lap_ms?: number | null;
  after_lap_number?: number | null;
  after_lap_ms?: number | null;
  caveat?: string | null;
};

/** One stop as the pit-loss estimate saw it. */
export type PitLossStop = {
  driver_code?: string | null;
  lap_number?: number | null;
  /** In-lap plus out-lap minus twice the baseline lap. Null when the stop does not qualify. */
  pit_loss_ms?: number | null;
  in_lap_ms?: number | null;
  out_lap_ms?: number | null;
  baseline_lap_ms?: number | null;
  baseline_lap_count?: number;
  /** Why the stop does not qualify, as a code; see `pitLossExclusionLabel`. */
  excluded_reason?: string | null;
};

/** What a stop costs against staying out, estimated from lap times (pipeline 2). */
export type PitLoss = {
  /** The median over the qualifying stops. Null when too few qualify. */
  estimate_ms?: number | null;
  spread_ms?: number | null;
  qualifying_stop_count: number;
  stop_count: number;
  minimum_stop_count?: number;
  excluded_stop_counts?: Record<string, number>;
  stops?: PitLossStop[];
};

/** Pit-lane transit times, summarised as what they are (pipeline 2). */
export type PitLaneTime = {
  median_ms?: number | null;
  fastest_ms?: number | null;
  slowest_ms?: number | null;
  timed_stop_count: number;
  stop_count: number;
};

/** `calculate_strategy` in backend/app/analysis/strategy.py. */
export type StrategyResult = {
  session_id: string;
  stints: Stint[];
  compound_usage: Record<string, number>;
  pit_stops: PitStop[];
  /**
   * Equal to `pit_loss.estimate_ms` from pipeline 2. Before that it was the
   * mean pit-lane time under the wrong name, so it is only a pit loss when
   * `pit_loss` is there too.
   */
  pit_loss_estimate_ms?: number | null;
  pit_loss?: PitLoss | null;
  pit_lane_time?: PitLaneTime | null;
  undercut_overcut: StrategyEstimate[];
  race_control_overlays: RaceControlMessage[];
  caveats: string[];
};

export type TrackDominanceMinisector = {
  index: number;
  start_distance_m: number;
  end_distance_m: number;
  midpoint: { x: number | null; y: number | null };
  winner_driver_code: string | null;
  segment_time_ms?: number | null;
  gap_to_next_ms?: number | null;
  /**
   * From pipeline 2 a driver is left out of a minisector where their
   * telemetry has no sample near one of its boundaries, so a missing driver
   * is the normal case and not every driver has a time everywhere.
   */
  driver_times_ms: { [driver: string]: number | null | undefined };
};

export type TrackDominanceResult = {
  session_id: string;
  representative_laps: Array<{ driver_code: string; lap_number: number; lap_time_ms?: number | null }>;
  /** Pipeline 2. Drivers with no clean lap whose telemetry runs line to line. */
  excluded_drivers?: string[];
  minisector_count: number;
  minisectors: TrackDominanceMinisector[];
  caveats: string[];
};

export type CornerDriverAnalysis = {
  driver_code: string;
  brake_start_m?: number | null;
  braking_distance_m?: number | null;
  entry_speed_kph?: number | null;
  apex_speed_kph?: number | null;
  exit_speed_kph?: number | null;
  speed_loss_kph?: number | null;
  brake_duration_ms?: number | null;
};

export type CornerAnalysisResult = {
  session_id: string;
  representative_laps: Array<{ driver_code: string; lap_number: number; lap_time_ms?: number | null }>;
  corners: Array<{
    corner_number: number;
    distance_m: number;
    x: number | null;
    y: number | null;
    drivers: CornerDriverAnalysis[];
  }>;
  caveats: string[];
};

export type CarPerformanceRow = {
  driver_code?: string;
  team: string;
  lap_number?: number | null;
  max_speed_kph?: number | null;
  p95_speed_kph?: number | null;
  low_speed_avg_kph?: number | null;
  medium_speed_avg_kph?: number | null;
  high_speed_avg_kph?: number | null;
  full_throttle_pct?: number | null;
  braking_pct?: number | null;
  drivers?: string[];
};

export type CarPerformanceResult = {
  session_id: string;
  drivers: CarPerformanceRow[];
  teams: CarPerformanceRow[];
  caveats: string[];
};

export type PacePredictionRow = {
  driver_code?: string;
  team: string;
  estimated_race_pace_ms?: number | null;
  gap_to_best_ms?: number | null;
  sample_count?: number;
  stint_count?: number;
  variability_ms?: number | null;
  confidence?: string | number | null;
  compounds?: string[];
  drivers?: string[];
};

export type PacePredictionResult = {
  session_id: string;
  available: boolean;
  session_type: string;
  drivers: PacePredictionRow[];
  teams: PacePredictionRow[];
  caveats: string[];
};

export type TelemetrySample = {
  session_id: string;
  driver_code: string;
  lap_number: number;
  distance_m: number;
  speed_kph?: number | null;
  throttle_pct?: number | null;
  brake?: boolean | null;
  rpm?: number | null;
  gear?: number | null;
  drs?: number | null;
  x?: number | null;
  y?: number | null;
  relative_time_ms?: number | null;
  session_time_ms?: number | null;
};

export type PositionReplayFrame = {
  session_id: string;
  frame_index: number;
  lap_number?: number | null;
  timestamp_ms?: number | null;
  positions: Array<Record<string, string | number | null>>;
};

export type EmptyStateResponse = {
  reason: string;
  action?: string | null;
  details?: Record<string, string>;
};

export type LiveDisabledResponse = {
  enabled: false;
  reason: string;
  setup: string[];
};
