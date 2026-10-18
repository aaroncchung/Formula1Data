"use client";

import { publishedSessions, sessionLabel } from "@/lib/calendar";
import type { PublishedIndex } from "@/lib/published/types";

type SessionSelectProps = {
  id: string;
  index: PublishedIndex;
  /** The session on the page, or null when there is none to show. */
  selectedKey: number | null;
  onChoose: (sessionKey: number) => void;
};

/**
 * Every published session, grouped by season and the most recent first. An
 * option's value is the session's key, so what the reader chooses is the
 * session itself and not a place in the calendar that can move.
 */
export function SessionSelect({ id, index, selectedKey, onChoose }: SessionSelectProps) {
  const sessions = publishedSessions(index);
  const years = [...new Set(sessions.map((session) => session.year))].sort((left, right) => right - left);
  const listed = selectedKey !== null && sessions.some((session) => session.key === selectedKey);

  return (
    <select
      id={id}
      className="control h-9 min-w-0 max-w-full flex-1 sm:max-w-[26rem]"
      value={selectedKey === null ? "" : String(selectedKey)}
      onChange={(event) => {
        if (event.target.value) {
          onChoose(Number(event.target.value));
        }
      }}
    >
      {selectedKey === null ? <option value="">Choose a session</option> : null}
      {/* The key on the page when the calendar does not list it: a session
          published a moment ago, or a key nothing is published under. */}
      {selectedKey !== null && !listed ? <option value={selectedKey}>Session {selectedKey}</option> : null}
      {years.map((year) => (
        <optgroup key={year} label={String(year)}>
          {sessions
            .filter((session) => session.year === year)
            .map((session) => (
              <option key={session.key} value={session.key}>
                {sessionLabel(session)}
              </option>
            ))}
        </optgroup>
      ))}
    </select>
  );
}
