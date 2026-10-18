"use client";

import { ErrorState } from "@/components/dashboard/ErrorState";
import { drawFailureDetail } from "@/components/published/failure-copy";
import { RetryButton } from "@/components/published/RetryButton";

import "./globals.css";

/**
 * The root layout threw, navigation and all, and this replaces it: so it has
 * its own <html> and <body> and brings its own styles. The link home is a
 * plain one, which loads the site afresh rather than through the router that
 * was part of what failed.
 */
export default function GlobalError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <html lang="en">
      <body>
        <main className="mx-auto w-full max-w-3xl space-y-3 px-4 py-12">
          <ErrorState title="The site could not be shown" detail={drawFailureDetail(error)} />
          <div className="flex flex-wrap items-center gap-3">
            <RetryButton onClick={reset} />
            {/* eslint-disable-next-line @next/next/no-html-link-for-pages -- a full load, on purpose */}
            <a className="text-sm font-semibold text-slate-200 underline-offset-4 hover:underline" href="/">
              Go to the home page
            </a>
          </div>
        </main>
      </body>
    </html>
  );
}
