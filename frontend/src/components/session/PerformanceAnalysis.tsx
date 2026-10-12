import { ChartPanel } from "@/components/charts/ChartPanel";
import { DataTable } from "@/components/data-table/DataTable";
import { EmptyState } from "@/components/dashboard/EmptyState";
import { AnalysisCaveats } from "@/components/session/AnalysisCaveats";
import { DriverBadge } from "@/components/session/Badges";
import { TeammateComparison } from "@/components/session/TeammateComparison";
import { TrackDominance } from "@/components/session/TrackDominance";
import { teamColorByDriver } from "@/lib/driver-style";
import { formatDelta, formatMs, formatNumber } from "@/lib/format";
import { cornerName, cornerPlace, cornerSourceNote, noBrakePoint, unavailableAnalyses, type AnalysisNotice } from "@/lib/performance-view";
import type { SessionPerformance } from "@/lib/published/artifacts";
import type { CarPerformance, CornerAnalysis, Driver, IdealLaps, PacePrediction } from "@/lib/published/types";

type Drivers = ReadonlyArray<Driver>;

/** Each analysis is null when the session does not have it. */
export function PerformanceAnalysis(props: SessionPerformance) {
  const notices = unavailableAnalyses(props);
  return (
    <div className="space-y-5">
      <div className="grid gap-5 2xl:grid-cols-2">
        <ChartPanel title="Ideal lap potential" description="Best sectors combined versus each driver’s best complete lap.">
          <IdealLapsView result={props.idealLaps} drivers={props.drivers} />
        </ChartPanel>
        <ChartPanel title="Team-mate race pace" description="The two drivers of each team, the quicker first, with each driver’s average lap.">
          <TeammateComparison result={props.teammateComparison} drivers={props.drivers} />
          <AnalysisCaveats caveats={props.teammateComparison?.caveats} />
        </ChartPanel>
      </div>
      {props.trackDominance?.minisectors.length ? (
        <ChartPanel title="Track dominance" description={`${props.trackDominance.minisector_count} minisectors coloured by the quickest representative lap.`}>
          <TrackDominance result={props.trackDominance} drivers={props.drivers} corners={props.corners} />
          <AnalysisCaveats caveats={props.trackDominance.caveats} />
        </ChartPanel>
      ) : null}
      {props.carPerformance?.drivers.length ? (
        <ChartPanel title="Car performance profile" description="Straight-line, corner-speed and control-use summary from representative laps.">
          <CarPerformanceView result={props.carPerformance} drivers={props.drivers} />
          <AnalysisCaveats caveats={props.carPerformance.caveats} />
        </ChartPanel>
      ) : null}
      {props.cornerAnalysis?.corners.length ? (
        <ChartPanel title="Corner analysis" description={cornerSourceNote(props.cornerAnalysis.corner_source)}>
          <CornerAnalysisView result={props.cornerAnalysis} drivers={props.drivers} />
          <AnalysisCaveats caveats={props.cornerAnalysis.caveats} />
        </ChartPanel>
      ) : null}
      {props.pacePrediction?.available && props.pacePrediction.drivers.length ? (
        <ChartPanel title="Race-pace prediction" description="Practice long-run estimate with sample coverage and variability shown explicitly.">
          <PacePredictionView result={props.pacePrediction} drivers={props.drivers} />
          <AnalysisCaveats caveats={props.pacePrediction.caveats} />
        </ChartPanel>
      ) : null}
      <NotShown notices={notices} />
    </div>
  );
}

/** The analyses with no panel above, each with its reason, so that none is missing without a word. */
function NotShown({ notices }: { notices: AnalysisNotice[] }) {
  if (notices.length === 0) {
    return null;
  }
  return (
    <section className="rounded border border-line bg-panel p-4" aria-label="Analyses not shown">
      <div className="eyebrow">Not shown for this session</div>
      <ul className="mt-3 space-y-1.5 text-sm text-slate-400">
        {notices.map((notice) => (
          <li key={notice.title}>
            <span className="font-semibold text-slate-200">{notice.title}.</span> {notice.reason}
          </li>
        ))}
      </ul>
    </section>
  );
}

function IdealLapsView({ result, drivers }: { result: IdealLaps | null; drivers: Drivers }) {
  if (!result) return <EmptyState title="Ideal laps unavailable" detail="This session has no ideal-lap analysis." />;
  if (!result.rows.length) return <EmptyState title="Ideal laps unavailable" detail="No driver has a time in every sector." />;
  const colors = teamColorByDriver(drivers);
  return (
    <DataTable rows={result.rows} columns={[
      { key: "driver", header: "Driver", render: (row) => <DriverBadge code={row.driver_code} color={colors[row.driver_code]} /> },
      { key: "ideal", header: "Ideal", align: "right", render: (row) => formatMs(row.ideal_lap_ms) },
      { key: "best", header: "Best lap", align: "right", render: (row) => formatMs(row.best_lap_ms) },
      { key: "left", header: "Time left", align: "right", render: (row) => <span className="text-amber">{formatDelta(row.delta_to_ideal_ms)}</span> }
    ]} />
  );
}

function CarPerformanceView({ result, drivers }: { result: CarPerformance; drivers: Drivers }) {
  const colors = teamColorByDriver(drivers);
  return <DataTable rows={result.drivers} columns={[
    { key: "driver", header: "Driver", render: (row) => <DriverBadge code={row.driver_code} color={colors[row.driver_code]} /> },
    { key: "max", header: "Max", align: "right", render: (row) => `${formatNumber(row.max_speed_kph, 0)} km/h` },
    { key: "low", header: "Low speed", align: "right", render: (row) => formatNumber(row.low_speed_avg_kph, 0) },
    { key: "medium", header: "Medium", align: "right", render: (row) => formatNumber(row.medium_speed_avg_kph, 0) },
    { key: "high", header: "High speed", align: "right", render: (row) => formatNumber(row.high_speed_avg_kph, 0) },
    { key: "throttle", header: "Full throttle", align: "right", render: (row) => percent(row.full_throttle_pct) },
    { key: "braking", header: "Braking", align: "right", render: (row) => percent(row.braking_pct) }
  ]} />;
}

function CornerAnalysisView({ result, drivers }: { result: CornerAnalysis; drivers: Drivers }) {
  const colors = teamColorByDriver(drivers);
  const rows = result.corners.flatMap((corner) =>
    corner.drivers.map((driver) => ({
      ...driver,
      corner: cornerName(corner, result.corner_source)
    }))
  );
  return <DataTable rows={rows} columns={[
    { key: "corner", header: "Corner", render: (row) => row.corner },
    // Where along the driver's own lap the corner is, so a row can be found on that lap's distance axis.
    { key: "at", header: "At", align: "right", render: (row) => metres(cornerPlace(row)) },
    { key: "driver", header: "Driver", render: (row) => <DriverBadge code={row.driver_code} color={colors[row.driver_code]} /> },
    {
      key: "brake",
      header: "Brake point",
      align: "right",
      // A driver can take a corner without braking for it; the row then has an apex and an exit and no braking.
      // And F1's feed can have no brake reading on the way in, which is not the same and is said apart.
      render: (row) => (row.brake_start_m === null ? <span className="text-slate-500">{noBrakePoint(row)}</span> : `${formatNumber(row.brake_start_m, 0)} m`)
    },
    { key: "distance", header: "Brake distance", align: "right", render: (row) => metres(row.braking_distance_m) },
    { key: "entry", header: "Entry", align: "right", render: (row) => speed(row.entry_speed_kph) },
    { key: "apex", header: "Apex", align: "right", render: (row) => speed(row.apex_speed_kph) },
    { key: "exit", header: "Exit", align: "right", render: (row) => speed(row.exit_speed_kph) }
  ]} />;
}

function PacePredictionView({ result, drivers }: { result: PacePrediction; drivers: Drivers }) {
  const colors = teamColorByDriver(drivers);
  return <DataTable rows={result.drivers} columns={[
    { key: "driver", header: "Driver", render: (row) => <DriverBadge code={row.driver_code} color={colors[row.driver_code]} /> },
    { key: "pace", header: "Est. pace", align: "right", render: (row) => formatMs(row.estimated_race_pace_ms) },
    { key: "gap", header: "Gap", align: "right", render: (row) => formatDelta(row.gap_to_best_ms) },
    { key: "runs", header: "Long runs", align: "right", render: (row) => row.stint_count },
    { key: "laps", header: "Laps", align: "right", render: (row) => row.sample_count },
    { key: "spread", header: "Variability", align: "right", render: (row) => formatDelta(row.variability_ms) },
    { key: "confidence", header: "Confidence", render: (row) => row.confidence }
  ]} />;
}

// A figure the analysis has none of is a dash on its own, without a unit after it.
function speed(kph: number | null): string {
  return kph === null ? "--" : `${formatNumber(kph, 0)} km/h`;
}

function metres(value: number | null): string {
  return value === null ? "--" : `${formatNumber(value, 0)} m`;
}

function percent(value: number | null): string {
  return value === null ? "--" : `${formatNumber(value, 1)}%`;
}
