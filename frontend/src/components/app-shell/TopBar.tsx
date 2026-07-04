"use client";

import { Menu, Server, Wifi } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { Sidebar } from "@/components/app-shell/Sidebar";
import { api, staticDataBasePath } from "@/lib/api";
import type { Session } from "@/types/domain";

export function TopBar() {
  const [open, setOpen] = useState(false);
  const [sessionLabel, setSessionLabel] = useState("Static artifacts");

  useEffect(() => {
    let ignore = false;

    api
      .catalog()
      .then((catalog) => {
        const session = selectPrimarySession(catalog.sessions);
        const meeting = catalog.meetings.find((item) => item.meeting_id === session?.meeting_id);
        if (!ignore && session) {
          setSessionLabel(`Latest artifact: ${session.year} ${meeting?.name || `Round ${session.round}`} ${session.name}`);
        }
      })
      .catch(() => {
        if (!ignore) {
          setSessionLabel("Static artifacts");
        }
      });

    return () => {
      ignore = true;
    };
  }, []);

  return (
    <header className="sticky top-0 z-20 border-b border-line/80 bg-carbon/90 backdrop-blur">
      <div className="flex min-h-16 items-center justify-between gap-4 px-4 sm:px-6 lg:px-8">
        <div className="flex items-center gap-3">
          <button
            className="grid h-9 w-9 place-items-center rounded border border-line bg-panel text-slate-200 lg:hidden"
            onClick={() => setOpen(true)}
            aria-label="Open navigation"
            type="button"
          >
            <Menu size={18} />
          </button>
          <div className="hidden text-sm text-slate-400 sm:block">{sessionLabel}</div>
        </div>
        <div className="flex min-w-0 items-center gap-2 text-xs text-slate-400">
          <Server size={15} className="text-aqua" />
          <span className="hidden sm:inline">Data</span>
          <span className="max-w-[55vw] truncate font-mono">{staticDataBasePath()}</span>
          <Wifi size={15} className="text-emerald-400" />
        </div>
      </div>
      {open ? (
        <div className="fixed inset-0 z-50 bg-black/60 lg:hidden" onClick={() => setOpen(false)}>
          <div className="h-full w-72 bg-carbon" onClick={(event) => event.stopPropagation()}>
            <div className="flex justify-end border-b border-line p-3">
              <Link className="rounded border border-line px-3 py-1 text-sm text-slate-300" href="/" onClick={() => setOpen(false)}>
                Close
              </Link>
            </div>
            <Sidebar />
          </div>
        </div>
      ) : null}
    </header>
  );
}

function selectPrimarySession(sessions: Session[]): Session | undefined {
  const available = sessions.filter((session) => session.status !== "missing");
  return [...(available.length ? available : sessions)]
    .sort((left, right) => sessionSortRank(left) - sessionSortRank(right))
    .at(-1);
}

function sessionSortRank(session: Session): number {
  const sessionOrder: Record<string, number> = { FP1: 1, FP2: 2, FP3: 3, SQ: 4, S: 5, Q: 6, R: 7 };
  return session.year * 10000 + session.round * 10 + (sessionOrder[session.type.toUpperCase()] || 0);
}
