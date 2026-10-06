/**
 * Calendars for the tests of the pages that are made from the index: the
 * published fixture's own, and ones built to hold a case it does not have.
 * Every one goes through the reader's parser, so a test reads what a page
 * would be handed.
 */

import { parseIndex } from "../../src/lib/published/parse.ts";
import { INDEX_KEY, PUBLISHED } from "./published-bucket.mjs";

/** The fixture's own index, parsed the way a page receives it. */
export function fixtureIndex() {
  return parseIndex(JSON.parse(PUBLISHED[INDEX_KEY]));
}

export function session(type, name, start, published = {}) {
  return { type, name, start_time_utc: start, ...published };
}

export function meeting(round, name, date, sessions, extra = {}) {
  return {
    round,
    name,
    official_name: null,
    country: null,
    location: null,
    date,
    format: "conventional",
    sessions,
    ...extra
  };
}

/** An index in the published shape. */
export function indexOf(seasons, unscheduled = []) {
  return parseIndex({ schema_version: 1, format_version: 1, seasons, unscheduled });
}

/** "Now" for `sampleIndex`: after the Austrian race and before the British qualifying. */
export const NOW = Date.parse("2026-07-01T00:00:00Z");

/**
 * A calendar with everything the pages have to tell apart: a complete and a
 * partial session, sessions that were run and are not published, sessions
 * still to come, a second season, and a published session the calendar has no
 * entry for.
 */
export function sampleIndex() {
  return indexOf(
    [
      {
        year: 2025,
        meetings: [
          meeting(24, "Abu Dhabi Grand Prix", "2025-12-07", [
            session("R", "Race", "2025-12-07T13:00:00Z", { session_key: 9001, complete: true })
          ])
        ]
      },
      {
        year: 2026,
        meetings: [
          meeting(
            7,
            "Barcelona Grand Prix",
            "2026-06-14",
            [
              session("Q", "Qualifying", "2026-06-13T14:00:00Z"),
              session("R", "Race", "2026-06-14T13:00:00Z", { session_key: 11300, complete: false })
            ],
            { country: "Spain", location: "Barcelona" }
          ),
          meeting(
            8,
            "Austrian Grand Prix",
            "2026-06-28",
            [
              session("S", "Sprint", "2026-06-27T10:00:00Z", { session_key: 11314, complete: true }),
              session("Q", "Qualifying", "2026-06-27T14:00:00Z"),
              session("R", "Race", "2026-06-28T13:00:00Z", { session_key: 11315, complete: true })
            ],
            { country: "Austria", location: "Spielberg", format: "sprint_qualifying" }
          ),
          meeting(
            9,
            "British Grand Prix",
            "2026-07-05",
            [
              session("Q", "Qualifying", "2026-07-04T15:00:00Z"),
              session("R", "Race", "2026-07-05T14:00:00Z")
            ],
            { country: "United Kingdom", location: "Silverstone" }
          )
        ]
      }
    ],
    [
      {
        session_key: 11200,
        year: 2026,
        type: "R",
        name: "Race",
        meeting_name: "Imola Grand Prix",
        start_time_utc: "2026-05-17T13:00:00Z",
        complete: true
      }
    ]
  );
}
