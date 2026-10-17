"use client";

import { Menu } from "lucide-react";
import { usePathname } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { GlobalSessionPicker, SessionPickerFallback } from "@/components/app-shell/GlobalSessionPicker";
import { Sidebar } from "@/components/app-shell/Sidebar";

export function TopBar() {
  const pathname = usePathname();
  // The page the drawer was opened on. The bar outlives the page under it, so
  // the drawer is open only on that page: once the reader is on another, by a
  // link in the drawer or by going back, it is closed.
  const [openOn, setOpenOn] = useState<string | null>(null);
  const open = openOn !== null && openOn === pathname;

  useEffect(() => {
    if (!open) {
      return;
    }
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpenOn(null);
      }
    }
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [open]);

  const close = () => setOpenOn(null);

  return (
    <header className="sticky top-0 z-20 border-b border-line/80 bg-carbon/90 backdrop-blur">
      <div className="flex min-h-16 items-center gap-3 px-4 py-3 sm:px-6 lg:px-8">
        <div className="flex shrink-0 items-center gap-3">
          <button
            className="grid h-9 w-9 place-items-center rounded border border-line bg-panel text-slate-200 lg:hidden"
            onClick={() => setOpenOn(pathname)}
            aria-label="Open navigation"
            aria-expanded={open}
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
        <div className="fixed inset-0 z-50 bg-black/60 lg:hidden" onClick={close}>
          <div
            className="h-full w-72 bg-carbon"
            role="dialog"
            aria-modal="true"
            aria-label="Navigation"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex justify-end border-b border-line p-3">
              <button type="button" className="rounded border border-line px-3 py-1 text-sm text-slate-300" onClick={close}>
                Close
              </button>
            </div>
            {/* A link to the page already open changes no path, and closes the drawer all the same. */}
            <Sidebar onNavigate={close} />
          </div>
        </div>
      ) : null}
    </header>
  );
}
