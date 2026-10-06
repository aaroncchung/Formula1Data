/**
 * Times as pandas prints them, which is how the published artifacts still
 * carry them (AR-05): a pit stop's `local_time`, a weather sample's
 * `timestamp` and a result's `gap` are `str(Timedelta)`, such as
 * `0 days 01:22:52.191000`, and a race-control message's `timestamp` is
 * `str(Timestamp)`, such as `2026-06-28 12:20:00`.
 *
 * The data is not fixed here. These functions read the strings so that a page
 * shows a time and not the string.
 */

// `-1 days +23:59:58.500000` is how pandas writes minus one and a half
// seconds: the day count carries the sign and the clock part is positive.
const PANDAS_DURATION = /^(-?\d+) days?,? \+?(\d{1,2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?$/;
const CLOCK_DURATION = /^(\d{1,3}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?$/;
const PANDAS_TIMESTAMP = /^\d{4}-\d{2}-\d{2}[ T](\d{2}:\d{2}:\d{2})/;

const MS_PER_SECOND = 1000;
const MS_PER_MINUTE = 60 * MS_PER_SECOND;
const MS_PER_HOUR = 60 * MS_PER_MINUTE;
const MS_PER_DAY = 24 * MS_PER_HOUR;

/**
 * A pandas duration in whole milliseconds, or null when the text is not one.
 * `NaT`, an empty string and anything else unreadable are all null: the
 * caller shows "no time", never a guess.
 */
export function parsePandasDuration(text: string | null | undefined): number | null {
  if (typeof text !== "string") {
    return null;
  }
  const trimmed = text.trim();
  const withDays = PANDAS_DURATION.exec(trimmed);
  if (withDays) {
    return Number(withDays[1]) * MS_PER_DAY + clockMs(withDays[2], withDays[3], withDays[4], withDays[5]);
  }
  const clockOnly = CLOCK_DURATION.exec(trimmed);
  return clockOnly ? clockMs(clockOnly[1], clockOnly[2], clockOnly[3], clockOnly[4]) : null;
}

function clockMs(hours: string, minutes: string, seconds: string, fraction: string | undefined): number {
  const fractionMs = fraction ? Math.round(Number(`0.${fraction}`) * MS_PER_SECOND) : 0;
  return Number(hours) * MS_PER_HOUR + Number(minutes) * MS_PER_MINUTE + Number(seconds) * MS_PER_SECOND + fractionMs;
}

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

/**
 * The time of day in a pandas timestamp, `12:20:00`, or null when the text is
 * not one. F1's feed is in UTC and the string carries no zone, so the caller
 * names the zone.
 */
export function clockTimeOfTimestamp(text: string | null | undefined): string | null {
  if (typeof text !== "string") {
    return null;
  }
  const match = PANDAS_TIMESTAMP.exec(text.trim());
  return match ? match[1] : null;
}

function pad(value: number): string {
  return String(value).padStart(2, "0");
}
