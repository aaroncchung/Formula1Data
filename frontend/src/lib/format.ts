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

