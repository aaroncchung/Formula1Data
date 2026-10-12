"use client";

import { Menu } from "lucide-react";
import Link from "next/link";
import { Suspense, useState } from "react";

import { GlobalSessionPicker, SessionPickerFallback } from "@/components/app-shell/GlobalSessionPicker";
import { Sidebar } from "@/components/app-shell/Sidebar";

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
        {/* The picker reads the query string to start on the session the page
            is about. The bar is part of every page, and Next refuses to export
            a page that reads the query outside a Suspense boundary. */}
        <Suspense fallback={<SessionPickerFallback />}>
          <GlobalSessionPicker />
        </Suspense>
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
