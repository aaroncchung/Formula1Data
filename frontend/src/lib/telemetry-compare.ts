/**
 * Two telemetry laps laid over each other by distance.
 *
 * A lap is published as parallel arrays, one entry for each sample, thinned
 * to a few hundred samples. Two laps never have their samples at the same
 * places, so lap B is read at the places of lap A's samples: what varies
 * smoothly (speed, throttle, engine speed, and the time the car got there)
 * is interpolated between B's two samples either side, and what is one value
 * or another (gear, brake, DRS) is taken from the nearer of the two.
 *
 * "The same place" is the same share of the lap, not the same number of
 * metres. A lap's distance is its own car's speed added up, and two laps of
 * one circuit come out at different lengths: in the 2026 Austrian GP
 * Antonelli's fastest lap measures 4,290.6 m and Verstappen's 4,309.8 m. Read
 * metre for metre, Verstappen would be 19 m short of the line where
 * Antonelli crosses it, and a lap that was 0.109 s slower would be drawn as
 * finishing 0.12 s ahead. So B's distances are scaled to A's lap length, the
 * two laps start and end together, and the time delta at the line is the
 * difference between the two lap times.
 *
 * Nothing is made up where a lap has no data. A lap can have a hole, a
 * stretch the car's data did not arrive for; nothing is interpolated across
 * one, and the charts break there. The publisher leaves a lap out altogether
 * when a hole in it is longer than five seconds, so the ones met here are a
 * few seconds at most. B has no value before its first sample.
 */

import type { Compound, TelemetryLap } from "./published/types.ts";

/** A lap in a comparison: whose it is, and what the session says of it. */
export type ComparedLap = {
  readonly driver_code: string;
  readonly team: string | null;
  readonly lap_number: number;
  readonly lap_time_ms: number | null;
  readonly compound: Compound | null;
};

export type TrackPoint = { readonly x: number; readonly y: number };

/**
 * Every array has one entry for each entry of `distance_m`. An entry is null
 * where that lap has nothing there: outside lap B's samples, inside a hole of
 * either lap, and in the row that marks a hole of lap A.
 */
export type TelemetryComparison = {
  readonly driver_a: ComparedLap;
  readonly driver_b: ComparedLap;
  /** Metres since the start of the lap, at lap A's samples. */
  readonly distance_m: number[];
  readonly speed_a: Array<number | null>;
  readonly speed_b: Array<number | null>;
  readonly throttle_a: Array<number | null>;
  readonly throttle_b: Array<number | null>;
  /** 1 while the brake is on, 0 while it is not. */
  readonly brake_a: Array<number | null>;
  readonly brake_b: Array<number | null>;
  readonly rpm_a: Array<number | null>;
  readonly rpm_b: Array<number | null>;
  readonly gear_a: Array<number | null>;
  readonly gear_b: Array<number | null>;
  /** 1 while DRS is open, 0 while it is not. Null for a session published without the channel, as every 2026 session is. */
  readonly drs_a: Array<number | null> | null;
  readonly drs_b: Array<number | null> | null;
  /** A minus B. */
  readonly delta_speed_kph: Array<number | null>;
  /** How much later B reached this point of the lap than A did, so positive is B behind. */
  readonly delta_time_ms: Array<number | null>;
  /** The line lap A drove, in the position data's units, where it has positions. */
  readonly track: TrackPoint[];
  readonly caveats: string[];
};

// Two samples further apart than this, and than a few of the lap's usual
// steps, have a hole between them. The first figure is for a lap thinned from
// a normal lap; the second for a lap so long that its usual step is already
// seconds, such as one spent behind a red flag.
const HOLE_MIN_MS = 2_000;
const HOLE_STEPS = 4;

/** The longest two neighbouring samples of a lap can be apart in time and still be joined. */
export function holeThresholdMs(timeMs: ReadonlyArray<number>): number {
  const steps: number[] = [];
  for (let index = 1; index < timeMs.length; index += 1) {
    steps.push(timeMs[index] - timeMs[index - 1]);
  }
  steps.sort((left, right) => left - right);
  const usual = steps.length ? steps[Math.floor(steps.length / 2)] : 0;
  return Math.max(HOLE_MIN_MS, HOLE_STEPS * usual);
}

type Reading = {
  time_ms: number;
  speed_kph: number;
  throttle_pct: number;
  rpm: number;
  gear: number;
  brake: number;
  drs: number | null;
};

/**
 * Compare two laps. `maxSamples` is how many samples a lap is published
 * with at most, which the comparison says of itself.
 */
export function compareLaps(
  a: { readonly meta: ComparedLap; readonly lap: TelemetryLap },
  b: { readonly meta: ComparedLap; readonly lap: TelemetryLap },
  maxSamples: number
): TelemetryComparison {
  const readB = readerOf(b.lap);
  const hole = holeThresholdMs(a.lap.time_ms);
  // Each lap's length by its own odometer. A lap has telemetry only when its
  // car data runs from its start to its end, so the last sample is at the line.
  const lengthA = a.lap.distance_m.at(-1) ?? 0;
  const lengthB = b.lap.distance_m.at(-1) ?? 0;
  const scale = lengthA > 0 && lengthB > 0 ? lengthB / lengthA : 1;
  const lastSample = a.lap.distance_m.length - 1;
  const rows: Array<{ distance: number; a: Reading | null; b: Reading | null }> = [];
  a.lap.distance_m.forEach((distance, index) => {
    const previous = index - 1;
    if (index > 0 && a.lap.time_ms[index] - a.lap.time_ms[previous] > hole) {
      // A row with nothing in it, part-way across the hole, so that a chart
      // stops lap A's line at one side and starts it again at the other.
      rows.push({ distance: (a.lap.distance_m[previous] + distance) / 2, a: null, b: null });
    }
    // The line itself is given exactly: scaled, it could land a rounding
    // error past B's last sample and read as nothing.
    rows.push({ distance, a: readingAt(a.lap, index), b: readB(index === lastSample ? lengthB : distance * scale) });
  });

  const of = (side: "a" | "b", field: Exclude<keyof Reading, "drs">) => rows.map((row) => row[side]?.[field] ?? null);
  const drs = (side: "a" | "b", lap: TelemetryLap) => (lap.drs === null ? null : rows.map((row) => row[side]?.drs ?? null));
  return {
    driver_a: a.meta,
    driver_b: b.meta,
    distance_m: rows.map((row) => row.distance),
    speed_a: of("a", "speed_kph"),
    speed_b: of("b", "speed_kph"),
    throttle_a: of("a", "throttle_pct"),
    throttle_b: of("b", "throttle_pct"),
    brake_a: of("a", "brake"),
    brake_b: of("b", "brake"),
    rpm_a: of("a", "rpm"),
    rpm_b: of("b", "rpm"),
    gear_a: of("a", "gear"),
    gear_b: of("b", "gear"),
    drs_a: drs("a", a.lap),
    drs_b: drs("b", b.lap),
    delta_speed_kph: rows.map((row) => (row.a && row.b ? round(row.a.speed_kph - row.b.speed_kph, 2) : null)),
    delta_time_ms: rows.map((row) => (row.a && row.b ? round(row.b.time_ms - row.a.time_ms, 1) : null)),
    track: trackOf(a.lap),
    caveats: [
      `The laps are laid over each other by the share of the lap covered. A lap's distance is its own car's speed added up, ${lengthLabel(lengthA)} for ${a.meta.driver_code} and ${lengthLabel(lengthB)} for ${b.meta.driver_code} here, so ${b.meta.driver_code}'s is scaled to ${a.meta.driver_code}'s.`,
      `${b.meta.driver_code}'s lap is read where ${a.meta.driver_code}'s samples are: speed, throttle, engine speed and time are interpolated between its two nearest samples, and gear, brake and DRS are taken from the nearer one.`,
      `A lap is published with at most ${maxSamples} samples, so a change that lasts less than the step between two of them can be missed.`
    ]
  };
}

/** The line a lap drove, from the samples that have a position. */
export function trackOf(lap: TelemetryLap): TrackPoint[] {
  const { x, y } = lap;
  if (x === null || y === null) {
    return [];
  }
  const points: TrackPoint[] = [];
  x.forEach((value, index) => {
    const other = y[index];
    // A sample taken before the position feed started, or after it stopped, has neither.
    if (value !== null && other !== null && other !== undefined) {
      points.push({ x: value, y: other });
    }
  });
  return points;
}

function readingAt(lap: TelemetryLap, index: number): Reading {
  return {
    time_ms: lap.time_ms[index],
    speed_kph: lap.speed_kph[index],
    throttle_pct: lap.throttle_pct[index],
    rpm: lap.rpm[index],
    gear: lap.gear[index],
    brake: lap.brake[index] ? 1 : 0,
    drs: lap.drs === null ? null : drsOpen(lap.drs[index])
  };
}

/** What a lap reads at a distance, or null where it has nothing there. */
function readerOf(lap: TelemetryLap): (distance: number) => Reading | null {
  const distances = lap.distance_m;
  const last = distances.length - 1;
  const hole = holeThresholdMs(lap.time_ms);
  return (target) => {
    if (last < 0 || target < distances[0] || target > distances[last]) {
      return null;
    }
    // The last sample at or before the target. Distance never decreases
    // along a lap, since it is integrated from speed.
    let low = 0;
    let high = last;
    while (low < high) {
      const middle = Math.ceil((low + high) / 2);
      if (distances[middle] <= target) {
        low = middle;
      } else {
        high = middle - 1;
      }
    }
    if (low === last || distances[low] === target) {
      return readingAt(lap, low);
    }
    const next = low + 1;
    if (lap.time_ms[next] - lap.time_ms[low] > hole) {
      return null;
    }
    const span = distances[next] - distances[low];
    const share = span > 0 ? (target - distances[low]) / span : 0;
    const between = (values: ReadonlyArray<number>) => values[low] + (values[next] - values[low]) * share;
    const nearer = readingAt(lap, share < 0.5 ? low : next);
    return {
      time_ms: between(lap.time_ms),
      speed_kph: between(lap.speed_kph),
      throttle_pct: between(lap.throttle_pct),
      rpm: between(lap.rpm),
      gear: nearer.gear,
      brake: nearer.brake,
      drs: nearer.drs
    };
  };
}

// F1's DRS code: 10, 12 and 14 are the flap open. 8 is a car that may open
// it and has not, and 0 to 3 are off.
function drsOpen(code: number): number {
  return code >= 10 ? 1 : 0;
}

function lengthLabel(metres: number): string {
  return `${Math.round(metres).toLocaleString("en-US")} m`;
}

function round(value: number, digits: number): number {
  const scale = 10 ** digits;
  return Math.round(value * scale) / scale;
}
