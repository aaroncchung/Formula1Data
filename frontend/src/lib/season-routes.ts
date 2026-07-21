const EXPLORE_PATH = "/seasons/explore";
const SESSION_CODES = new Set(["FP1", "FP2", "FP3", "SQ", "S", "Q", "R"]);

export type ExploreTarget =
  | { kind: "season"; year: number }
  | { kind: "meeting"; year: number; round: number }
  | { kind: "session"; year: number; round: number; session: string }
  | { kind: "error"; detail: string };

type SearchParamsReader = Pick<URLSearchParams, "get">;

export function seasonHref(year: number): string {
  return exploreHref({ year });
}

export function meetingHref(year: number, round: number): string {
  return exploreHref({ year, round });
}

export function sessionHref(
  year: number,
  round: number,
  session: string,
  fragment = ""
): string {
  const href = exploreHref({ year, round, session: session.toUpperCase() });
  if (!fragment) return href;
  return `${href}${fragment.startsWith("#") ? fragment : `#${fragment}`}`;
}

export function parseExploreTarget(params: SearchParamsReader): ExploreTarget {
  const year = positiveInteger(params.get("year"));
  if (year === null) {
    return { kind: "error", detail: "A positive integer year is required." };
  }

  const roundValue = params.get("round");
  const sessionValue = params.get("session");
  if (roundValue === null) {
    return sessionValue === null
      ? { kind: "season", year }
      : { kind: "error", detail: "A round is required when a session is provided." };
  }

  const round = positiveInteger(roundValue);
  if (round === null) {
    return { kind: "error", detail: "Round must be a positive integer." };
  }
  if (sessionValue === null) {
    return { kind: "meeting", year, round };
  }

  const session = sessionValue.trim().toUpperCase();
  if (!SESSION_CODES.has(session)) {
    return { kind: "error", detail: `Unsupported session code: ${sessionValue || "(empty)"}.` };
  }
  return { kind: "session", year, round, session };
}

function exploreHref(values: { year: number; round?: number; session?: string }): string {
  const params = new URLSearchParams({ year: String(values.year) });
  if (values.round !== undefined) params.set("round", String(values.round));
  if (values.session) params.set("session", values.session);
  return `${EXPLORE_PATH}?${params}`;
}

function positiveInteger(value: string | null): number | null {
  if (value === null || !/^\d+$/.test(value)) return null;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null;
}
