"use client";

import { Menu, Server, Wifi } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Sidebar } from "@/components/app-shell/Sidebar";
import { staticDataBasePath } from "@/lib/api";

export function TopBar() {
  const [open, setOpen] = useState(false);
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
          <div className="hidden text-sm text-slate-400 sm:block">Session: 2025 Monaco GP Race</div>
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
