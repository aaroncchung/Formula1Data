/**
 * How a number of milliseconds is written on a page.
 *
 * Every time in the published format is a number of milliseconds: a length
 * of time, or a reading of the session clock, which is milliseconds after
 * `clock_zero_utc` in the session's summary. Format 1 carried them as text
 * the way pandas prints a duration, and this module used to parse that; now
 * it only formats.
 */

const MS_PER_SECOND = 1000;
const MS_PER_MINUTE = 60 * MS_PER_SECOND;
const MS_PER_HOUR = 60 * MS_PER_MINUTE;

/**
 * A reading of the session clock as `1:22:52`. The clock starts with F1's
 * timing feed, about an hour before a race does, so this is neither a time of
 * day nor the time since the start.
 */
export function formatSessionClock(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || !Number.isFinite(ms)) {
    return "--";
  }
  const sign = ms < 0 ? "-" : "";
  const totalSeconds = Math.floor(Math.abs(ms) / MS_PER_SECOND);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  return `${sign}${hours}:${pad(minutes)}:${pad(seconds)}`;
}

/** The session clock to the minute, `1:22`, for an axis where seconds are noise. */
export function formatSessionClockMinutes(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || !Number.isFinite(ms)) {
    return "--";
  }
  const totalMinutes = Math.floor(Math.abs(ms) / MS_PER_MINUTE);
  return `${ms < 0 ? "-" : ""}${Math.floor(totalMinutes / 60)}:${pad(totalMinutes % 60)}`;
}

/** A length of time to the millisecond: `21.552`, `1:02.677` or `1:26:37.979`. */
export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || !Number.isFinite(ms)) {
    return "--";
  }
  const sign = ms < 0 ? "-" : "";
  const total = Math.round(Math.abs(ms));
  const hours = Math.floor(total / MS_PER_HOUR);
  const minutes = Math.floor((total % MS_PER_HOUR) / MS_PER_MINUTE);
  const seconds = ((total % MS_PER_MINUTE) / MS_PER_SECOND).toFixed(3);
  if (hours > 0) {
    return `${sign}${hours}:${pad(minutes)}:${seconds.padStart(6, "0")}`;
  }
  if (minutes > 0) {
    return `${sign}${minutes}:${seconds.padStart(6, "0")}`;
  }
  return `${sign}${seconds}`;
}

/**
 * A length of time with its unit where it needs one: `21.552s`, and from a
 * minute up `1:02.677`, which reads as a time without help.
 */
export function formatElapsed(ms: number | null | undefined): string {
  const text = formatDuration(ms);
  return text === "--" || text.includes(":") ? text : `${text}s`;
}

function pad(value: number): string {
  return String(value).padStart(2, "0");
}
