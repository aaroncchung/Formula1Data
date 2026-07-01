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
  duration_ms?: number | null;
  local_time?: string | null;
};

export type WeatherSample = {
  session_id: string;
  lap_number?: number | null;
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

export type TyreDegradationRow = {
  driver_code: string;
  compound: string;
  stint: number;
  degradation_ms_per_lap?: number | null;
  r_squared?: number | null;
  sample_count: number;
  stint_length: number;
  caveats: string[];
};

export type TyreDegradationResult = {
  session_id: string;
  rows: TyreDegradationRow[];
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
};

export type QualifyingDeltaResult = {
  session_id: string;
  driver_a: string;
  driver_b: string;
  sector_delta_ms: Record<string, number | null>;
  telemetry?: TelemetryComparison | null;
  caveats: string[];
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
