export function formatMs(value?: number | null): string {
  if (value === null || value === undefined) {
    return "--";
  }
  const minutes = Math.floor(value / 60000);
  const seconds = ((value % 60000) / 1000).toFixed(3).padStart(6, "0");
  return `${minutes}:${seconds}`;
}

export function formatDelta(value?: number | null): string {
  if (value === null || value === undefined) {
    return "--";
  }
  const sign = value > 0 ? "+" : "";
  return `${sign}${(value / 1000).toFixed(3)}s`;
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

