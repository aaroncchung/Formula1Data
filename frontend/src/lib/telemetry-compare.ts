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
 * difference between the times the two laps' telemetry runs for.
 *
 * That is the difference between the two lap times for every lap whose
 * telemetry runs for its lap time, which is not quite all of them. A first
 * lap's time is the classification's, counted from the start signal, and its
 * telemetry is on the session clock, from the moment F1's feed has the
 * session start: the two are a quarter of a second apart in most races and
 * more than a second in some, and not by the same amount for every car. In
 * the 2026 Australian GP Albon's first lap is timed at 1:39.376 and Bearman's
 * at 1:39.765, 0.389 s apart, and their telemetry ends 0.455 s apart. The
 * telemetry is the one clock both cars are on, so the delta is left on it,
 * and where the delta at the line is then not the difference between the two
 * lap times, the comparison says so and gives both (`clockNote`). Two first
 * laps whose clocks are out by the same amount, as most of one race's are,
 * still end the difference of their lap times apart, and nothing is said.
 *
 * A place is not always one moment. A car in its pit box has dozens of
 * samples at one distance, and the published distance can even step back a
 * tenth of a metre there. Two things follow.
 *
 * - A lap's distance is read as the furthest the car had got by each sample,
 *   so it never goes down. Looked up as published, the sample after a stop
 *   that sits a tenth of a metre back was found on the way into the box:
 *   in the 2026 Canadian GP, Bearman's lap 30 compared with itself was 23
 *   seconds apart from itself at that sample.
 * - Where both cars stand at the same place, B is read as far into its stop
 *   as A is into its own, and no further than the end of it. The longer stop
 *   then shows as time lost while it lasts, and as the difference between the
 *   two stops from there on. Where only B stands at a place A drives through,
 *   B is read as it arrives, and its stop is in the delta at the next place.
 *
 * Nothing is made up where a lap has no data. A lap can have a hole, a
 * stretch the car's data did not arrive for; nothing is interpolated across
 * one, and the charts break there: a row with nothing for that lap is put
 * between the rows either side of the hole, since a chart joins whatever two
 * rows it is given. The publisher leaves a lap out altogether
 * when a hole in it is longer than five seconds, so the ones met here are a
 * few seconds at most. B has no value before its first sample. And a channel
 * that has no entry for a sample has no value there: a brake that is not
 * known to be on is not drawn as off.
 */

import { formatMs } from "./format.ts";
import type { Compound, TelemetryLap } from "./published/types.ts";

/** A lap in a comparison: whose it is, and what the session says of it. */
export type ComparedLap = {
  readonly driver_code: string;
  readonly team: string | null;
  readonly lap_number: number;
  readonly lap_time_ms: number | null;
  readonly compound: Compound | null;
};

/** A place on the line a lap drove, and how far round the lap it is, on the distance axis the lap is drawn on. */
export type TrackPoint = { readonly x: number; readonly y: number; readonly distance_m: number };

/**
 * Figures of one lap, from its own samples and from nothing else.
 *
 * Not from the lap as the comparison reads it. Lap B is read at lap A's
 * places, between its own samples, so its highest reading there is lower
 * than its highest sample unless A happens to have a sample at that place:
 * in the 2026 Austrian GP Verstappen's lap 57 reaches 319.9 km/h, and laid
 * under Hamilton's lap 48 its trace reaches 318.7. The card took the second,
 * and the same lap showed 319 km/h as lap B and 320 as lap A.
 */
export type LapFigures = {
  /** The highest speed of any sample, or null for a lap with no speed. */
  readonly max_speed_kph: number | null;
  /** The share of the lap's samples with the throttle at 98% or more, of those that have a throttle value. */
  readonly full_throttle_pct: number | null;
};

const FULL_THROTTLE_PCT = 98;

export function lapFigures(lap: TelemetryLap): LapFigures {
  const known = (values: ReadonlyArray<number | null>) => values.filter((value): value is number => value !== null && value !== undefined);
  const speeds = known(lap.speed_kph);
  const throttle = known(lap.throttle_pct);
  return {
    max_speed_kph: speeds.length ? Math.max(...speeds) : null,
    full_throttle_pct: throttle.length ? (throttle.filter((value) => value >= FULL_THROTTLE_PCT).length / throttle.length) * 100 : null
  };
}

/**
 * Every array has one entry for each entry of `distance_m`. An entry is null
 * where that lap has nothing there: outside lap B's samples, inside a hole of
 * either lap, in the row that marks a hole of either lap, and where the lap's
 * channel has no entry for the sample.
 */
export type TelemetryComparison = {
  readonly driver_a: ComparedLap;
  readonly driver_b: ComparedLap;
  /** Each lap's own figures: the same for a lap whichever side of the comparison it is on. */
  readonly figures_a: LapFigures;
  readonly figures_b: LapFigures;
  /** Metres since the start of the lap, at lap A's samples. It never goes down. */
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

/** What a lap reads at one moment. A channel is null where it has no value to give. */
type Reading = {
  time_ms: number;
  speed_kph: number | null;
  throttle_pct: number | null;
  rpm: number | null;
  gear: number | null;
  brake: number | null;
  drs: number | null;
};

/** A lap as the comparison reads it. */
type Samples = {
  readonly lap: TelemetryLap;
  /** How many samples have both a time and a distance; the rest cannot be placed. */
  readonly count: number;
  readonly time: ReadonlyArray<number>;
  /** How far the car had got by each sample: the published distance, kept from going down. */
  readonly published: ReadonlyArray<number>;
  /**
   * The same, counted from the line: less what the lap's distance reads at
   * its first sample, when that sample is at time nought. It does not read
   * nought there. A lap's distance is counted from the sample before the
   * line, and the line comes out a fraction of a metre either side of it,
   * another fraction on each lap. A lap whose data begins after the line has
   * no reading at the line, and its distances are taken as they are.
   *
   * Everything that places one lap on another reads this, and nothing else
   * shifts a distance: the same lap twice gives the same numbers twice, so a
   * place that is exactly a sample's place stays exactly that.
   */
  readonly distance: ReadonlyArray<number>;
  /**
   * For each sample, the first and the last sample at the same distance.
   * They are the sample itself unless the car was standing there.
   */
  readonly firstAt: ReadonlyArray<number>;
  readonly lastAt: ReadonlyArray<number>;
  readonly holeMs: number;
};

function samplesOf(lap: TelemetryLap): Samples {
  const count = Math.min(lap.time_ms.length, lap.distance_m.length);
  const time = lap.time_ms.slice(0, count);
  const published: number[] = [];
  for (let index = 0; index < count; index += 1) {
    published.push(index === 0 ? lap.distance_m[0] : Math.max(published[index - 1], lap.distance_m[index]));
  }
  const atTheLine = count > 0 && time[0] === 0 ? published[0] : 0;
  const distance = published.map((furthest) => furthest - atTheLine);
  const firstAt: number[] = [];
  for (let index = 0; index < count; index += 1) {
    firstAt.push(index > 0 && distance[index - 1] === distance[index] ? firstAt[index - 1] : index);
  }
  const lastAt: number[] = distance.map((_, index) => index);
  for (let index = count - 2; index >= 0; index -= 1) {
    if (distance[index + 1] === distance[index]) {
      lastAt[index] = lastAt[index + 1];
    }
  }
  return { lap, count, time, published, distance, firstAt, lastAt, holeMs: holeThresholdMs(time) };
}

/**
 * How long the car had been standing at a sample's place when the sample was
 * taken, or null when it was not standing there: it has no other sample at
 * that distance.
 */
function standingMs(samples: Samples, index: number): number | null {
  const first = samples.firstAt[index];
  return first === samples.lastAt[index] ? null : samples.time[index] - samples.time[first];
}

/**
 * Compare two laps. `maxSamples` is how many samples a lap is published
 * with at most, which the comparison says of itself.
 */
export function compareLaps(
  a: { readonly meta: ComparedLap; readonly lap: TelemetryLap },
  b: { readonly meta: ComparedLap; readonly lap: TelemetryLap },
  maxSamples: number
): TelemetryComparison {
  const samplesA = samplesOf(a.lap);
  const samplesB = samplesOf(b.lap);
  const readB = readerOf(samplesB);
  // Each lap's length by its own odometer, from the line (`Samples.distance`).
  // A lap has telemetry only when its car data runs from its start to its
  // end, so the last sample is at the line.
  const lastSample = samplesA.count - 1;
  const lastOfB = samplesB.count - 1;
  const lengthA = samplesA.distance[lastSample] ?? 0;
  const lengthB = samplesB.distance[lastOfB] ?? 0;
  const scale = lengthA > 0 && lengthB > 0 ? lengthB / lengthA : 1;
  const holesOfB = holesOf(samplesB);
  const rows: Array<{ distance: number; a: Reading | null; b: Reading | null }> = [];
  // What B read at A's sample before this one.
  let before: Reading | null = null;
  samplesA.distance.forEach((distance, index) => {
    const previous = index - 1;
    const holeOfA = index > 0 && samplesA.time[index] - samplesA.time[previous] > samplesA.holeMs;
    if (holeOfA) {
      // A row with nothing in it, part-way across the hole, so that a chart
      // stops lap A's line at one side and starts it again at the other.
      rows.push({ distance: (samplesA.published[previous] + samplesA.published[index]) / 2, a: null, b: null });
    }
    // The line itself is given exactly: scaled, it could land a rounding
    // error past B's last sample and read as nothing. Every sample of A that
    // is at the line, and a lap can have more than one: a published distance
    // has one decimal, and a lap's last samples can be closer than that.
    const place = lengthA > 0 && distance === lengthA ? lengthB : distance * scale;
    // And where A's lap ends, so does B's: at its last sample, and not at
    // the first of several that its distance puts at the line. That is what
    // makes the delta at the line the difference between the two lap times.
    const ofB =
      index === lastSample
        ? lastOfB >= 0
          ? readingAt(b.lap, lastOfB)
          : null
        : readB(place, standingMs(samplesA, index));
    if (!holeOfA && before !== null && ofB !== null && holesOfB.some((hole) => before!.time_ms <= hole.from && ofB.time_ms >= hole.to)) {
      // A hole of B that falls between two of A's samples: B reads well at
      // both, and a chart given the two rows would draw B straight across
      // what its data did not arrive for. A row with nothing for B goes
      // between them. A has no hole here, so it is read half-way, where its
      // own line passes anyway.
      rows.push({
        distance: (samplesA.published[previous] + samplesA.published[index]) / 2,
        a: readingBetween(samplesA, previous, 0.5),
        b: null
      });
    }
    before = ofB;
    // The chart's axis is lap A's distance as it is published.
    rows.push({ distance: samplesA.published[index], a: readingAt(a.lap, index), b: ofB });
  });

  const of = (side: "a" | "b", field: Exclude<keyof Reading, "drs">) => rows.map((row) => row[side]?.[field] ?? null);
  const drs = (side: "a" | "b", lap: TelemetryLap) => (lap.drs === null ? null : rows.map((row) => row[side]?.drs ?? null));
  return {
    driver_a: a.meta,
    driver_b: b.meta,
    figures_a: lapFigures(a.lap),
    figures_b: lapFigures(b.lap),
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
    delta_speed_kph: rows.map((row) => {
      const speedA = row.a?.speed_kph ?? null;
      const speedB = row.b?.speed_kph ?? null;
      return speedA === null || speedB === null ? null : round(speedA - speedB, 2);
    }),
    delta_time_ms: rows.map((row) => (row.a && row.b ? round(row.b.time_ms - row.a.time_ms, 1) : null)),
    track: trackOf(a.lap),
    caveats: [
      `The laps are laid over each other by the share of the lap covered. A lap's distance is its own car's speed added up, ${lengthLabel(lengthA)} for ${a.meta.driver_code} and ${lengthLabel(lengthB)} for ${b.meta.driver_code} here, so ${b.meta.driver_code}'s is scaled to ${a.meta.driver_code}'s.`,
      `${b.meta.driver_code}'s lap is read where ${a.meta.driver_code}'s samples are: speed, throttle, engine speed and time are interpolated between its two nearest samples, and gear, brake and DRS are taken from the nearer one.`,
      `A lap is published with at most ${maxSamples} samples, so a change that lasts less than the step between two of them can be missed.`,
      ...clockNote({ meta: a.meta, samples: samplesA }, { meta: b.meta, samples: samplesB })
    ]
  };
}

/** The stretches of a lap its data did not arrive for, as the times of the samples either side. */
function holesOf(samples: Samples): Array<{ from: number; to: number }> {
  const holes: Array<{ from: number; to: number }> = [];
  for (let index = 1; index < samples.count; index += 1) {
    if (samples.time[index] - samples.time[index - 1] > samples.holeMs) {
      holes.push({ from: samples.time[index - 1], to: samples.time[index] });
    }
  }
  return holes;
}

type ClockedLap = { meta: ComparedLap; samples: Samples };

/**
 * What to say when the delta at the line is not the difference between the
 * two lap times a reader has in front of them, as one caveat, or nothing
 * when it is, or when either lap has no time to be apart from.
 *
 * The delta is between the two laps' telemetry. It ends the difference of
 * the lap times apart whenever each lap's telemetry runs for its lap time,
 * and also when both are out by the same amount: said of every lap that is
 * out, it was said of pairs for which it is not so, and of a lap laid over
 * itself. So it goes by the two differences, and names the lap or laps that
 * make them differ.
 */
function clockNote(a: ClockedLap, b: ClockedLap): string[] {
  const runsFor = ({ samples }: ClockedLap) => (samples.count > 0 ? samples.time[samples.count - 1] : null);
  const [endOfA, endOfB] = [runsFor(a), runsFor(b)];
  if (a.meta.lap_time_ms === null || b.meta.lap_time_ms === null || endOfA === null || endOfB === null) {
    return [];
  }
  const atTheLine = Math.round(endOfB - endOfA);
  const lapTimesApart = Math.round(b.meta.lap_time_ms - a.meta.lap_time_ms);
  if (atTheLine === lapTimesApart) {
    return [];
  }
  const apart = [a, b].flatMap((lap) => {
    const { meta } = lap;
    const end = runsFor(lap);
    if (meta.lap_time_ms === null || end === null || Math.round(end) === Math.round(meta.lap_time_ms)) {
      return [];
    }
    const why =
      meta.lap_number === 1
        ? "a first lap is timed by the classification from the start signal, and its telemetry is on the session clock"
        : "the timing and the session clock do not agree on where this lap began";
    return [`${meta.driver_code}'s lap ${meta.lap_number} is timed at ${formatMs(meta.lap_time_ms)} and its telemetry runs for ${formatMs(end)}: ${why}.`];
  });
  return [
    `The time delta is between the telemetry of the two laps: at the line it is ${seconds(atTheLine)}, and the two lap times are ${seconds(lapTimesApart)} apart. ${apart.join(" ")}`
  ];
}

/** A difference in seconds to the thousandth, with its sign: `+0.455 s`. */
function seconds(ms: number): string {
  return `${ms > 0 ? "+" : ms < 0 ? "-" : ""}${(Math.abs(ms) / 1000).toFixed(3)} s`;
}

/** The line a lap drove, from the samples that have a position. */
export function trackOf(lap: TelemetryLap): TrackPoint[] {
  const { x, y } = lap;
  if (x === null || y === null) {
    return [];
  }
  const { distance } = samplesOf(lap);
  const points: TrackPoint[] = [];
  distance.forEach((along, index) => {
    const value = x[index];
    const other = y[index];
    // A sample taken before the position feed started, or after it stopped, has neither.
    if (value !== null && value !== undefined && other !== null && other !== undefined) {
      points.push({ x: value, y: other, distance_m: along });
    }
  });
  return points;
}

/**
 * A channel's entry for a sample, or null when the channel is shorter than
 * the lap's clock. The schema allows that; a reader must not fill it in.
 */
function entry<Value>(channel: ReadonlyArray<Value>, index: number): Value | null {
  return index < channel.length ? channel[index] : null;
}

function readingAt(lap: TelemetryLap, index: number): Reading {
  const brake = entry(lap.brake, index);
  const drs = lap.drs === null ? null : entry(lap.drs, index);
  return {
    time_ms: lap.time_ms[index],
    speed_kph: entry(lap.speed_kph, index),
    throttle_pct: entry(lap.throttle_pct, index),
    rpm: entry(lap.rpm, index),
    gear: entry(lap.gear, index),
    // Not "off" for a sample the channel says nothing of.
    brake: brake === null ? null : brake ? 1 : 0,
    drs: drs === null ? null : drsOpen(drs)
  };
}

/**
 * What a lap reads part of the way from one sample to the next, or null when
 * the two have a hole between them.
 */
function readingBetween(samples: Samples, low: number, share: number): Reading | null {
  const { lap, time } = samples;
  const next = low + 1;
  if (time[next] - time[low] > samples.holeMs) {
    return null;
  }
  const from = readingAt(lap, low);
  const to = readingAt(lap, next);
  const between = (start: number | null, end: number | null) => (start === null || end === null ? null : start + (end - start) * share);
  const nearer = share < 0.5 ? from : to;
  return {
    time_ms: from.time_ms + (to.time_ms - from.time_ms) * share,
    speed_kph: between(from.speed_kph, to.speed_kph),
    throttle_pct: between(from.throttle_pct, to.throttle_pct),
    rpm: between(from.rpm, to.rpm),
    gear: nearer.gear,
    brake: nearer.brake,
    drs: nearer.drs
  };
}

/**
 * What a lap reads at a moment of a standstill, which is the samples `first`
 * to `last`, all at one distance. A moment before or after it is its first or
 * its last sample: a car is not read as standing after it has left.
 */
function readingWhileStanding(samples: Samples, first: number, last: number, moment: number): Reading | null {
  const { time } = samples;
  const at = Math.min(Math.max(moment, time[first]), time[last]);
  let low = first;
  while (low < last && time[low + 1] <= at) {
    low += 1;
  }
  if (low === last || time[low] === at) {
    return readingAt(samples.lap, low);
  }
  return readingBetween(samples, low, (at - time[low]) / (time[low + 1] - time[low]));
}

/**
 * What a lap reads at a place, or null where it has nothing there.
 * `standing` is how long the car it is compared with had been standing at
 * that place, or null when that car was driving through it.
 */
function readerOf(samples: Samples): (place: number, standing: number | null) => Reading | null {
  const { distance, time, firstAt } = samples;
  const last = samples.count - 1;
  return (place, standing) => {
    if (last < 0 || place < distance[0] || place > distance[last]) {
      return null;
    }
    // The last sample at or before the place. The search relies on the
    // distance never going down, which `samplesOf` has seen to.
    let low = 0;
    let high = last;
    while (low < high) {
      const middle = Math.ceil((low + high) / 2);
      if (distance[middle] <= place) {
        low = middle;
      } else {
        high = middle - 1;
      }
    }
    if (distance[low] !== place) {
      return readingBetween(samples, low, (place - distance[low]) / (distance[low + 1] - distance[low]));
    }
    const first = firstAt[low];
    if (first === low) {
      return readingAt(samples.lap, low);
    }
    // This car stood at exactly this place, from `first` to `low`. Against a
    // car driving through it, what compares is the moment it arrived. Against
    // a car standing there too, the same moment of the stop.
    return standing === null ? readingAt(samples.lap, first) : readingWhileStanding(samples, first, low, time[first] + standing);
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
