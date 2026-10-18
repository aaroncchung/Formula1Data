export const APP_NAME = "Formula 1 Data";

export type NavItem = {
  href: string;
  label: string;
  /** Other paths that belong to this entry, so that it stays highlighted on them. */
  under?: ReadonlyArray<string>;
};

export const NAV_ITEMS: ReadonlyArray<NavItem> = [
  { href: "/", label: "Dashboard" },
  // A season, a meeting and a session are each a page of their own, named in
  // the query string, and all of them are reached from the list of seasons.
  { href: "/seasons", label: "Seasons", under: ["/season", "/meeting", "/session"] },
  { href: "/telemetry", label: "Telemetry" },
  { href: "/strategy", label: "Strategy" },
  { href: "/standings", label: "Standings" },
  { href: "/drivers", label: "Drivers" },
  { href: "/teams", label: "Teams" },
  { href: "/circuits", label: "Circuits" }
];

export const COMPOUND_COLORS: Record<string, string> = {
  SOFT: "#ef4444",
  MEDIUM: "#fbbf24",
  HARD: "#f8fafc",
  INTERMEDIATE: "#22c55e",
  WET: "#38bdf8",
  UNKNOWN: "#94a3b8"
};

