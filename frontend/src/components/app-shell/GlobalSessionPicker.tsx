"use client";

import { AlertTriangle, ArrowRight, CalendarRange, Database } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";

import { usePublishedIndex } from "@/components/calendar/usePublishedIndex";
import type { IndexState } from "@/components/calendar/usePublishedIndex";
import { failureDetail, failureTitle } from "@/components/published/failure-copy";
import { publishedDataBaseUrl } from "@/lib/published/config";
import { sessionHref } from "@/lib/published/lookup";
import { pickerKeyForQuery, pickerSelection, pickerYears } from "@/lib/session-picker";
import type { PickerSelection, PickerYear } from "@/lib/session-picker";

type Choice = { readonly location: string; readonly key: number };

/**
 * The session picker in the bar at the top of every page.
 *
 * It offers the sessions the published calendar lists as published, read in
 * the browser, and opens the chosen one by its key. It used to read the
 * catalog that was in the repository when the site was built, so a session
 * published later could not be picked (AR-07).
 */
export function GlobalSessionPicker() {
  const pathname = usePathname();
  const query = useSearchParams();
  const router = useRouter();

  // Where the reader is. The bar outlives the page under it, so the calendar
  // is read again whenever this changes, and a choice made in the picker
  // lasts only until then: on a new page the picker shows that page's session.
  const location = `${pathname}?${query.toString()}`;
  const { state } = usePublishedIndex(location);
  const [choice, setChoice] = useState<Choice | null>(null);

  const index = state.status === "ready" ? state.index : null;
  const years = useMemo(() => (index ? pickerYears(index) : []), [index]);
  // The one thing held is a session key. The season and the event shown are
  // read back from the calendar for it, so nothing here keeps a round.
  const chosenKey = choice?.location === location ? choice.key : index ? pickerKeyForQuery(index, query) : null;
  const selection = pickerSelection(years, chosenKey);

  return (
    <>
      <SessionPickerControls
        years={years}
        selection={selection}
        placeholder={placeholderFor(state, years)}
        onChoose={(key) => setChoice({ location, key })}
        onOpen={(key) => router.push(sessionHref({ kind: "key", sessionKey: key }))}
      />
      <DataSourceStatus state={state} />
    </>
  );
}

/** What the bar shows before the query string can be read, which is also what the exported HTML holds. */
export function SessionPickerFallback() {
  return (
    <SessionPickerControls years={[]} selection={null} placeholder="Loading sessions" onChoose={noop} onOpen={noop} />
  );
}

function noop() {}

function placeholderFor(state: IndexState, years: ReadonlyArray<PickerYear>): string | null {
  if (state.status === "loading") {
    return "Loading sessions";
  }
  if (state.status === "failed") {
    return "Sessions unavailable";
  }
  return years.length === 0 ? "No sessions published" : null;
}

type SessionPickerControlsProps = {
  years: ReadonlyArray<PickerYear>;
  selection: PickerSelection | null;
  /** Shown in the event control when there is nothing to choose, saying why. */
  placeholder: string | null;
  onChoose: (sessionKey: number) => void;
  onOpen: (sessionKey: number) => void;
};

function SessionPickerControls({ years, selection, placeholder, onChoose, onOpen }: SessionPickerControlsProps) {
  const disabled = selection === null;

  function chooseYear(value: string) {
    // Choosing a season is choosing its most recent session.
    const year = years.find((item) => String(item.year) === value);
    if (year) {
      onChoose(year.key);
    }
  }

  return (
    <div className="flex min-w-0 flex-1 items-center gap-2" role="group" aria-label="Session selection">
      <CalendarRange className="hidden shrink-0 text-slate-500 xl:block" size={16} aria-hidden="true" />
      <label className="sr-only" htmlFor="global-season">
        Season
      </label>
      <select
        id="global-season"
        className="control hidden h-9 w-[82px] shrink-0 sm:block"
        value={selection ? String(selection.year.year) : ""}
        onChange={(event) => chooseYear(event.target.value)}
        disabled={disabled}
      >
        {years.map((year) => (
          <option key={year.year} value={year.year}>
            {year.year}
          </option>
        ))}
      </select>
      <label className="sr-only" htmlFor="global-event">
        Event
      </label>
      <select
        id="global-event"
        className="control h-9 min-w-0 flex-1 sm:max-w-[250px]"
        value={selection ? String(selection.event.key) : ""}
        // An event's value is the key of its last published session, so
        // choosing an event is choosing that session.
        onChange={(event) => onChoose(Number(event.target.value))}
        disabled={disabled}
      >
        {selection ? (
          selection.year.events.map((event) => (
            <option key={event.key} value={event.key}>
              {event.label}
            </option>
          ))
        ) : (
          <option value="">{placeholder ?? ""}</option>
        )}
      </select>
      <label className="sr-only" htmlFor="global-session">
        Session
      </label>
      <select
        id="global-session"
        className="control h-9 w-[90px] shrink-0 sm:w-[132px]"
        value={selection ? String(selection.session.key) : ""}
        onChange={(event) => onChoose(Number(event.target.value))}
        disabled={disabled}
      >
        {(selection?.event.sessions ?? []).map((session) => (
          <option key={session.key} value={session.key}>
            {session.label}
          </option>
        ))}
      </select>
      <button
        className="icon-button h-9 w-9 shrink-0"
        type="button"
        onClick={() => {
          if (selection) {
            onOpen(selection.session.key);
          }
        }}
        disabled={disabled}
        aria-label="Open selected session"
        title="Open selected session"
      >
        <ArrowRight size={16} aria-hidden="true" />
      </button>
    </div>
  );
}

/**
 * Whether published data can be read at all, where it is visible from every
 * page. A failure is shown at every width; the page under the bar says the
 * same thing in full.
 */
function DataSourceStatus({ state }: { state: IndexState }) {
  if (state.status === "failed") {
    return (
      <div
        className="flex shrink-0 items-center gap-2 text-xs font-semibold text-redline"
        role="status"
        title={`${failureTitle(state.failure)}. ${failureDetail(state.failure)}`}
      >
        <AlertTriangle size={14} aria-hidden="true" />
        <span className="sr-only sm:not-sr-only">Data unavailable</span>
      </div>
    );
  }
  if (state.status === "loading") {
    return null;
  }
  return (
    <div
      className="hidden shrink-0 items-center gap-2 text-xs text-slate-500 2xl:flex"
      title={`Data source: ${publishedDataBaseUrl()}`}
    >
      <Database size={14} className="text-aqua" aria-hidden="true" />
      <span>Published data</span>
    </div>
  );
}
