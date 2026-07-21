"use client";

import { ArrowRight, CalendarRange } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { api } from "@/lib/api";
import { parseExploreTarget, sessionHref } from "@/lib/season-routes";
import type { CatalogArtifact } from "@/lib/static-api-core";

export function GlobalSessionPicker() {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [catalog, setCatalog] = useState<CatalogArtifact | null>(null);
  const [year, setYear] = useState("");
  const [meetingId, setMeetingId] = useState("");
  const [sessionId, setSessionId] = useState("");

  useEffect(() => {
    let ignore = false;
    api.catalog().then((nextCatalog) => {
      if (ignore) return;
      setCatalog(nextCatalog);
      const routeSession = selectRouteSession(nextCatalog, pathname, searchParams);
      const selected = routeSession || selectLatestSession(nextCatalog);
      if (selected) {
        setYear(String(selected.year));
        setMeetingId(selected.meeting_id);
        setSessionId(selected.session_id);
      }
    }).catch(() => setCatalog(null));
    return () => {
      ignore = true;
    };
  }, [pathname, searchParams]);

  const years = useMemo(
    () => [...new Set((catalog?.sessions || []).map((item) => item.year))].sort((a, b) => b - a),
    [catalog]
  );
  const meetings = useMemo(
    () => (catalog?.meetings || [])
      .filter((item) => item.year === Number(year) && catalog?.sessions.some((session) => session.meeting_id === item.meeting_id && session.status !== "missing"))
      .sort((a, b) => a.round - b.round),
    [catalog, year]
  );
  const meeting = meetings.find((item) => item.meeting_id === meetingId);
  const sessions = useMemo(
    () => (catalog?.sessions || [])
      .filter((item) => item.meeting_id === meetingId && item.status !== "missing")
      .sort((a, b) => sessionOrder(a.type) - sessionOrder(b.type)),
    [catalog, meetingId]
  );

  function changeYear(nextYear: string) {
    const availableSessions = (catalog?.sessions || []).filter((item) => item.year === Number(nextYear) && item.status !== "missing");
    const nextMeeting = (catalog?.meetings || [])
      .filter((item) => item.year === Number(nextYear) && availableSessions.some((session) => session.meeting_id === item.meeting_id))
      .sort((a, b) => b.round - a.round)[0];
    const nextSession = availableSessions
      .filter((item) => item.meeting_id === nextMeeting?.meeting_id)
      .sort((a, b) => sessionOrder(a.type) - sessionOrder(b.type))[0];
    setYear(nextYear);
    setMeetingId(nextMeeting?.meeting_id || "");
    setSessionId(nextSession?.session_id || "");
  }

  function changeMeeting(nextMeetingId: string) {
    const nextSession = (catalog?.sessions || [])
      .filter((item) => item.meeting_id === nextMeetingId && item.status !== "missing")
      .sort((a, b) => sessionOrder(a.type) - sessionOrder(b.type))[0];
    setMeetingId(nextMeetingId);
    setSessionId(nextSession?.session_id || "");
  }

  function openSession() {
    const selected = catalog?.sessions.find((item) => item.session_id === sessionId);
    if (selected) {
      const currentHash = window.location.hash;
      const section = pathname.startsWith("/telemetry")
        ? "#telemetry"
        : pathname.startsWith("/strategy")
          ? "#strategy"
          : ["#telemetry", "#strategy"].includes(currentHash)
            ? currentHash
            : "";
      router.push(sessionHref(selected.year, selected.round, selected.type, section));
    }
  }

  return (
    <div className="flex min-w-0 flex-1 items-center gap-2" aria-label="Global session selection">
      <CalendarRange className="hidden shrink-0 text-slate-500 xl:block" size={16} aria-hidden="true" />
      <label className="sr-only" htmlFor="global-season">Season</label>
      <select
        id="global-season"
        className="control hidden h-9 w-[82px] shrink-0 sm:block"
        value={year}
        onChange={(event) => changeYear(event.target.value)}
        disabled={!catalog}
      >
        {years.map((item) => <option key={item} value={item}>{item}</option>)}
      </select>
      <label className="sr-only" htmlFor="global-event">Event</label>
      <select
        id="global-event"
        className="control h-9 min-w-0 flex-1 sm:max-w-[250px]"
        value={meetingId}
        onChange={(event) => changeMeeting(event.target.value)}
        disabled={!catalog}
      >
        {meetings.map((item) => <option key={item.meeting_id} value={item.meeting_id}>R{item.round} · {item.name}</option>)}
      </select>
      <label className="sr-only" htmlFor="global-session">Session</label>
      <select
        id="global-session"
        className="control h-9 w-[90px] shrink-0 sm:w-[132px]"
        value={sessionId}
        onChange={(event) => setSessionId(event.target.value)}
        disabled={!catalog || !meeting}
      >
        {sessions.map((item) => <option key={item.session_id} value={item.session_id}>{item.type} · {item.name}</option>)}
      </select>
      <button
        className="icon-button h-9 w-9 shrink-0"
        type="button"
        onClick={openSession}
        disabled={!sessionId}
        aria-label="Open selected session"
        title="Open selected session"
      >
        <ArrowRight size={16} />
      </button>
    </div>
  );
}

function selectLatestSession(catalog: CatalogArtifact) {
  const order: Record<string, number> = { FP1: 1, FP2: 2, FP3: 3, SQ: 4, S: 5, Q: 6, R: 7 };
  return [...catalog.sessions]
    .filter((item) => item.status !== "missing")
    .sort((a, b) => (a.year * 10000 + a.round * 10 + (order[a.type.toUpperCase()] || 0)) - (b.year * 10000 + b.round * 10 + (order[b.type.toUpperCase()] || 0)))
    .at(-1);
}

function selectRouteSession(
  catalog: CatalogArtifact,
  pathname: string,
  searchParams: Pick<URLSearchParams, "get">
) {
  const prettyRoute = pathname.match(/^\/seasons\/(\d{4})\/(\d+)\/([^/]+)/);
  if (prettyRoute) {
    return catalog.sessions.find(
      (item) =>
        item.year === Number(prettyRoute[1]) &&
        item.round === Number(prettyRoute[2]) &&
        item.type.toLowerCase() === prettyRoute[3].toLowerCase() &&
        item.status !== "missing"
    );
  }
  if (pathname !== "/seasons/explore") return null;

  const target = parseExploreTarget(searchParams);
  const candidates = catalog.sessions.filter((item) => {
    if (item.status === "missing" || target.kind === "error") return false;
    if (item.year !== target.year) return false;
    if (target.kind === "season") return true;
    if (item.round !== target.round) return false;
    return target.kind !== "session" || item.type.toUpperCase() === target.session;
  });
  return target.kind === "season"
    ? candidates.sort(compareSessions).at(-1)
    : candidates.sort((left, right) => sessionOrder(left.type) - sessionOrder(right.type))[0];
}

function compareSessions(left: CatalogArtifact["sessions"][number], right: CatalogArtifact["sessions"][number]) {
  return (
    left.year * 10000 + left.round * 10 + sessionOrder(left.type) -
    (right.year * 10000 + right.round * 10 + sessionOrder(right.type))
  );
}

function sessionOrder(type: string) {
  const order: Record<string, number> = { FP1: 1, FP2: 2, FP3: 3, SQ: 4, S: 5, Q: 6, R: 7 };
  return order[type.toUpperCase()] || 99;
}
