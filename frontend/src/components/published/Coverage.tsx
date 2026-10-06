import { AlertTriangle, CheckCircle2 } from "lucide-react";

import type { Coverage } from "@/lib/published/types";

/**
 * Published and complete are separate states: a session below a coverage bar
 * is still published, as partial, and the page has to say so wherever the
 * figures are shown. Both components read the pointer of the pinned
 * generation, not the index, which only repeats the verdict and can lag.
 */
export function CoverageBadge({ coverage }: { coverage: Coverage }) {
  return coverage.complete ? (
    <span className="inline-flex items-center gap-2 rounded border border-aqua/40 bg-aqua/10 px-3 py-1.5 text-xs font-semibold text-aqua">
      <CheckCircle2 size={14} aria-hidden="true" />
      Complete data
    </span>
  ) : (
    <span className="inline-flex items-center gap-2 rounded border border-amber/40 bg-amber/10 px-3 py-1.5 text-xs font-semibold text-amber">
      <AlertTriangle size={14} aria-hidden="true" />
      Partial data
    </span>
  );
}

export function CoverageShortfalls({ coverage }: { coverage: Coverage }) {
  if (coverage.complete) {
    return null;
  }
  return (
    <section className="mb-5 rounded border border-amber/40 bg-amber/10 p-5" aria-label="Data coverage">
      <div className="flex items-start gap-3">
        <AlertTriangle className="mt-0.5 shrink-0 text-amber" size={18} aria-hidden="true" />
        <div className="min-w-0">
          <h2 className="font-semibold text-white">This session is published with partial data</h2>
          <p className="mt-1 text-sm text-slate-300">
            Not everything F1 publishes for this session arrived in full when it was fetched. Figures that depend on
            what is listed here may be missing or wrong.
          </p>
          {coverage.shortfalls.length === 0 ? (
            <p className="mt-3 text-sm text-slate-400">The publication does not say what fell short.</p>
          ) : (
            <ul className="mt-3 space-y-1.5 text-sm text-slate-200">
              {coverage.shortfalls.map((shortfall, index) => (
                <li key={index} className="flex flex-wrap items-baseline gap-x-2">
                  <span className="font-mono text-amber">{shortfall.bar.replaceAll("_", " ")}</span>
                  <span className="font-semibold text-white">{shortfall.driver ?? "Whole session"}</span>
                  <span className="text-slate-300">{shortfall.detail}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </section>
  );
}
