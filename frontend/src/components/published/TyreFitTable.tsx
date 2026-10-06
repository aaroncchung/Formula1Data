import { DataTable } from "@/components/data-table/DataTable";
import { AnalysisCaveats } from "@/components/session/AnalysisCaveats";
import { CompoundBadge, DriverBadge } from "@/components/session/Badges";
import { formatNumber } from "@/lib/format";
import { formatRate, tyreFit } from "@/lib/tyre-chart";
import type { TyreDegradationResult, TyreDegradationRow } from "@/types/domain";

/**
 * Every stint's degradation fit, with what the fit rests on.
 *
 * A stint whose fit was not reported keeps its row, so the table accounts for
 * every stint, and its rate cells say "not reported" with the reason. They
 * never hold a number: a slope that could not be pinned down is not a small
 * slope.
 */
export function TyreFitTable({ degradation, colors }: { degradation: TyreDegradationResult; colors: Record<string, string | null | undefined> }) {
  return (
    <div>
      <div className="mb-3">
        <h3 className="font-bold text-white">Degradation model</h3>
        <p className="mt-1 text-sm text-slate-500">
          The fitted slope of each stint, the fuel correction added to it, and the adjusted tyre rate, with how well the
          fit is pinned down.
        </p>
      </div>
      <DataTable
        rows={degradation.rows}
        emptyText="No tyre stints with clean laps."
        columns={[
          { key: "driver", header: "Driver", render: (row) => <DriverBadge code={row.driver_code} color={colors[row.driver_code]} /> },
          { key: "compound", header: "Compound", render: (row) => <CompoundBadge compound={row.compound} /> },
          { key: "stint", header: "Stint", align: "right", render: (row) => row.stint },
          { key: "laps", header: "Laps fitted", align: "right", render: (row) => row.sample_count },
          { key: "raw", header: "Raw slope", align: "right", render: (row) => <Reported row={row}>{formatRate(row.raw_slope_ms_per_lap)}</Reported> },
          { key: "fuel", header: "Fuel correction", align: "right", render: (row) => <Reported row={row}>{formatRate(row.fuel_correction_ms_per_lap)}</Reported> },
          { key: "adjusted", header: "Tyre rate", align: "right", render: (row) => <RateCell row={row} /> },
          { key: "error", header: "Std error", align: "right", render: (row) => (row.slope_standard_error_ms_per_lap == null ? "--" : `± ${formatNumber(row.slope_standard_error_ms_per_lap, 1)}`) },
          { key: "spread", header: "Scatter", align: "right", render: (row) => (row.residual_spread_ms == null ? "--" : `${formatNumber(row.residual_spread_ms, 0)} ms`) },
          { key: "fit", header: "R²", align: "right", render: (row) => formatNumber(row.r_squared, 2) },
          { key: "excluded", header: "Outliers", align: "right", render: (row) => row.excluded_outlier_count ?? 0 }
        ]}
      />
      <AnalysisCaveats caveats={degradation.caveats} />
    </div>
  );
}

/** A figure that belongs to a reported fit, and a dash for a fit that was not. */
function Reported({ row, children }: { row: TyreDegradationRow; children: React.ReactNode }) {
  return tyreFit(row).status === "reported" ? (
    <span className="whitespace-nowrap">{children}</span>
  ) : (
    <span className="text-slate-600">--</span>
  );
}

function RateCell({ row }: { row: TyreDegradationRow }) {
  const fit = tyreFit(row);
  if (fit.status === "reported") {
    return <span className="whitespace-nowrap font-mono font-semibold text-aqua">{formatRate(fit.rate_ms_per_lap)}</span>;
  }
  return <span className="inline-block min-w-[14rem] max-w-xs text-left text-xs text-slate-500">{fit.reason}</span>;
}
