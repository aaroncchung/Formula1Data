/**
 * The tabs of a session page, and how a URL names one.
 *
 * The ids are the fragments the old dashboard used (`#lap-times`,
 * `#position-replay`), so a link to a tab made before this page existed still
 * opens that tab. Which files each tab reads is in artifacts.ts.
 */

export const SESSION_TABS = [
  { id: "overview", label: "Overview" },
  { id: "lap-times", label: "Lap Times" },
  { id: "race-pace", label: "Race Pace" },
  { id: "performance", label: "Performance" },
  { id: "strategy", label: "Strategy" },
  { id: "telemetry", label: "Telemetry" },
  { id: "position-replay", label: "Position Replay" },
  { id: "weather", label: "Weather" },
  { id: "race-control", label: "Race Control" },
  { id: "results", label: "Results" }
] as const;

export type SessionTabId = (typeof SESSION_TABS)[number]["id"];

/** The tab a page opens on when its URL names none. */
export const DEFAULT_SESSION_TAB: SessionTabId = "overview";

/**
 * The tab a URL fragment names, or null when it names none. Read as the old
 * dashboard read it: case does not matter, and a space may stand for a
 * hyphen, so `#Lap%20Times` is the lap-times tab.
 */
export function tabFromHash(hash: string): SessionTabId | null {
  let wanted: string;
  try {
    wanted = decodeURIComponent(hash.replace(/^#/, ""));
  } catch {
    // A fragment that is not valid percent-encoding names nothing.
    return null;
  }
  const id = wanted.trim().toLowerCase().replaceAll(/[\s_]+/g, "-");
  return SESSION_TABS.find((tab) => tab.id === id)?.id ?? null;
}

/** The fragment that names a tab. */
export function hashOfTab(tab: SessionTabId): string {
  return `#${tab}`;
}
