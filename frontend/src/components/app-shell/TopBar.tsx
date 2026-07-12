"use client";

import { Database, Menu } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { GlobalSessionPicker } from "@/components/app-shell/GlobalSessionPicker";
import { Sidebar } from "@/components/app-shell/Sidebar";
import { staticDataBasePath } from "@/lib/api";

export function TopBar() {
  const [open, setOpen] = useState(false);

  return (
    <header className="sticky top-0 z-20 border-b border-line/80 bg-carbon/90 backdrop-blur">
      <div className="flex min-h-16 items-center gap-3 px-4 py-3 sm:px-6 lg:px-8">
        <div className="flex shrink-0 items-center gap-3">
          <button
            className="grid h-9 w-9 place-items-center rounded border border-line bg-panel text-slate-200 lg:hidden"
            onClick={() => setOpen(true)}
            aria-label="Open navigation"
            type="button"
          >
            <Menu size={18} />
          </button>
        </div>
        <GlobalSessionPicker />
        <div className="hidden shrink-0 items-center gap-2 text-xs text-slate-500 2xl:flex" title={`Data source: ${staticDataBasePath()}`}>
          <Database size={14} className="text-aqua" aria-hidden="true" />
          <span>Static data ready</span>
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
