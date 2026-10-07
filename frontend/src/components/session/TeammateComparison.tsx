import { EmptyState } from "@/components/dashboard/EmptyState";
import { DriverBadge } from "@/components/session/Badges";
import { teamColorByDriver } from "@/lib/driver-style";
import { formatMs } from "@/lib/format";
import { teammateBasis, teammateGap, teammateGapText } from "@/lib/teammate-view";
import type { Driver, TeammateComparison as TeammateComparisonResult, TeammateComparisonRow } from "@/lib/published/types";

/**
 * The two drivers of each team, compared on the laps both ran cleanly.
 *
 * A row can have no gap, when too few laps match; it then says so, with the
 * row's own reason, in place of a number.
 */
export function TeammateComparison({ result, drivers }: { result: TeammateComparisonResult | null; drivers: ReadonlyArray<Driver> }) {
  if (!result?.rows.length) {
    return <EmptyState title="Team-mate comparison unavailable" detail="This session does not contain two comparable drivers per team." />;
  }
  const colors = teamColorByDriver(drivers);
  return (
    <div className="space-y-2">
      {result.rows.map((row) => (
        <TeamRow key={row.team} row={row} colors={colors} />
      ))}
    </div>
  );
}

function TeamRow({ row, colors }: { row: TeammateComparisonRow; colors: Record<string, string | null | undefined> }) {
  const gap = teammateGap(row);
  const basis = teammateBasis(row);
  return (
    <div className="rounded-md border border-line/70 bg-carbon/40 p-3">
      <div className="grid gap-3 sm:grid-cols-[130px_1fr_auto] sm:items-center">
        <div className="truncate text-sm font-semibold text-slate-300">{row.team}</div>
        <div className="flex flex-wrap items-center gap-3">
          {row.drivers.map((driver) => (
            <div
              key={driver.driver_code}
              className="flex items-center gap-2"
              title={`${driver.clean_lap_count} clean laps in all`}
            >
              <DriverBadge code={driver.driver_code} color={colors[driver.driver_code]} />
              <span className="font-mono text-xs text-slate-400">{formatMs(driver.average_lap_ms)}</span>
            </div>
          ))}
        </div>
        <div className={`font-mono text-sm font-bold ${gap.status === "reported" ? "text-amber" : "text-slate-500"}`}>
          {teammateGapText(gap)}
        </div>
      </div>
      {gap.status === "none" ? <p className="mt-2 text-xs text-slate-500">{gap.reason}</p> : null}
      {gap.status !== "none" ? <p className="mt-2 text-xs text-slate-500">Over {basis}</p> : null}
    </div>
  );
}
