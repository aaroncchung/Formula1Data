/**
 * A lap time, to the thousandth: `1:15.521`.
 *
 * Rounded to whole milliseconds before it is split into minutes and seconds.
 * An average has a decimal, and split first, 119,999.6 ms was one minute and
 * 59.9996 seconds, which prints as `1:60.000`.
 */
export function formatMs(value?: number | null): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "--";
  }
  const whole = Math.round(Math.abs(value));
  const minutes = Math.floor(whole / 60000);
  const seconds = ((whole % 60000) / 1000).toFixed(3).padStart(6, "0");
  return `${value < 0 && whole > 0 ? "-" : ""}${minutes}:${seconds}`;
}

/**
 * A gap in seconds with its sign, `+1.234s`. Rounded to the millisecond
 * before the sign is chosen, as `formatMs` is: a gap of 0.4 ms read
 * "+0.000s", and one of -0.4 ms "-0.000s".
 */
export function formatDelta(value?: number | null): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "--";
  }
  const whole = Math.round(Math.abs(value));
  const sign = whole === 0 ? "" : value > 0 ? "+" : "-";
  return `${sign}${(whole / 1000).toFixed(3)}s`;
}

/** A length of time in seconds with no sign in front, `1.234s`: a spread, not a gap to anything. */
export function formatSeconds(value?: number | null): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "--";
  }
  const whole = Math.round(Math.abs(value));
  return `${value < 0 && whole > 0 ? "-" : ""}${(whole / 1000).toFixed(3)}s`;
}

export function formatNumber(value?: number | null, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "--";
  }
  return value.toFixed(digits);
}

export function compactDate(value?: string | null): string {
  if (!value) {
    return "TBC";
  }
  return new Intl.DateTimeFormat("en", { month: "short", day: "numeric", year: "numeric" }).format(
    new Date(value)
  );
}

/**
 * When a session was run, for the heading of a page about it. A moment is
 * given in the reader's own time zone with the zone named, like
 * `sessionStart`, and with its year: "Mar 7, 2026, 11:00 PM EST". A bare date
 * there would be the reader's date for a race run somewhere else, with nothing
 * to say so, and a day off from the meeting's own. A value that is only a day,
 * which is all the calendar has for a session it has not timed, is that day.
 * `timeZone` is for tests; a page leaves it out.
 */
export function sessionWhen(value?: string | null, timeZone?: string): string {
  if (value && /^\d{4}-\d{2}-\d{2}$/.test(value)) {
    return calendarDay(value);
  }
  const time = value ? Date.parse(value) : Number.NaN;
  if (Number.isNaN(time)) {
    return "TBC";
  }
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
    timeZone
  }).format(time);
}

/**
 * A day of the calendar, such as a meeting's `2026-06-28`. It is formatted in
 * UTC because it is a date and not a moment: read as a moment, it shows as
 * the day before to anyone west of Greenwich.
 */
export function calendarDay(value?: string | null): string {
  const time = value ? Date.parse(value) : Number.NaN;
  if (Number.isNaN(time)) {
    return "TBC";
  }
  return new Intl.DateTimeFormat("en", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" }).format(
    time
  );
}

/**
 * When a session starts, in the reader's own time zone, which is named:
 * "Sun, Jun 28, 9:00 AM EDT". `timeZone` is for tests; a page leaves it out.
 */
export function sessionStart(value?: string | null, timeZone?: string): string {
  const time = value ? Date.parse(value) : Number.NaN;
  if (Number.isNaN(time)) {
    return "Time to be confirmed";
  }
  return new Intl.DateTimeFormat("en", {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
    timeZone
  }).format(time);
}

