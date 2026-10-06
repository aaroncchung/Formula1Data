import { ChartPanel } from "@/components/charts/ChartPanel";
import { DriverMark } from "@/components/charts/DriverMark";
import { DataTable } from "@/components/data-table/DataTable";
import { EmptyState } from "@/components/dashboard/EmptyState";
import { DriverBadge } from "@/components/session/Badges";
import { driverStyle, teamColorByDriver, teamDriverStyles } from "@/lib/driver-style";
import { formatDelta, formatMs, formatNumber } from "@/lib/format";
import { boundsOf, fitBounds, project, type Viewport } from "@/lib/track-map";
import type {
  CarPerformanceResult,
  CornerAnalysisResult,
  Driver,
  IdealLapsResult,
  PacePredictionResult,
  TeammateComparisonResult,
  TrackDominanceResult
} from "@/types/domain";

/** The dash of the second team-mate, scaled up for the thick line of the track map. */
const TRACK_DASH = "12 7";
const DOMINANCE_VIEWPORT: Viewport = { width: 600, height: 400, padding: 25 };

type PerformanceAnalysisProps = {
  drivers: Driver[];
  idealLaps: IdealLapsResult | null;
  teammateComparison: TeammateComparisonResult | null;
  trackDominance: TrackDominanceResult | null;
  cornerAnalysis: CornerAnalysisResult | null;
  carPerformance: CarPerformanceResult | null;
  pacePrediction: PacePredictionResult | null;
};

export function PerformanceAnalysis(props: PerformanceAnalysisProps) {
  const hasNewAnalysis = Boolean(
    props.trackDominance?.minisectors.length || props.cornerAnalysis?.corners.length ||
    props.carPerformance?.drivers.length || props.pacePrediction?.drivers.length
  );
  return (
    <div className="space-y-5">
      <div className="grid gap-5 2xl:grid-cols-2">
        <ChartPanel title="Ideal lap potential" description="Best sectors combined versus each driver’s best complete lap.">
          <IdealLapsView result={props.idealLaps} drivers={props.drivers} />
        </ChartPanel>
        <ChartPanel title="Team-mate race pace" description="Average clean-lap comparison within each team.">
          <TeammateView result={props.teammateComparison} drivers={props.drivers} />
          <AnalysisCaveats caveats={props.teammateComparison?.caveats} />
        </ChartPanel>
      </div>
      {props.trackDominance?.minisectors.length ? (
        <ChartPanel title="Track dominance" description={`${props.trackDominance.minisector_count} minisectors coloured by the quickest representative lap.`}>
          <TrackDominanceView result={props.trackDominance} drivers={props.drivers} />
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
        <ChartPanel title="Corner analysis" description="Braking, apex and exit metrics detected from representative telemetry laps.">
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
      {!hasNewAnalysis ? (
        <EmptyState
          title="Advanced telemetry models are not generated yet"
          detail="Ideal-lap and team-mate analysis are shown above. Re-ingest this session to add track dominance, corner, car-performance, and pace-prediction artifacts."
        />
      ) : null}
    </div>
  );
}

function IdealLapsView({ result, drivers }: { result: IdealLapsResult | null; drivers: Driver[] }) {
  if (!result?.rows.length) return <EmptyState title="Ideal laps unavailable" detail="No sector-combination artifact exists for this session." />;
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

function TeammateView({ result, drivers }: { result: TeammateComparisonResult | null; drivers: Driver[] }) {
  if (!result?.rows.length) return <EmptyState title="Team-mate comparison unavailable" detail="This session does not contain two comparable drivers per team." />;
  const colors = teamColorByDriver(drivers);
  return (
    <div className="space-y-2">
      {result.rows.map((row) => (
        <div key={row.team} className="grid gap-3 rounded-md border border-line/70 bg-carbon/40 p-3 sm:grid-cols-[130px_1fr_auto] sm:items-center">
          <div className="truncate text-sm font-semibold text-slate-300">{row.team}</div>
          <div className="flex flex-wrap items-center gap-3">
            {row.drivers.map((driver) => (
              <div key={driver.driver_code} className="flex items-center gap-2">
                <DriverBadge code={driver.driver_code} color={colors[driver.driver_code]} />
                <span className="font-mono text-xs text-slate-400">{formatMs(driver.average_lap_ms)}</span>
              </div>
            ))}
          </div>
          <div className="font-mono text-sm font-bold text-amber">{formatDelta(row.gap_ms)}</div>
        </div>
      ))}
    </div>
  );
}

function TrackDominanceView({ result, drivers }: { result: TrackDominanceResult; drivers: Driver[] }) {
  // The map identifies a driver by the line alone, so team-mates need the
  // shared solid/dashed styles here, not just the team colour.
  const styles = teamDriverStyles(drivers);
  const sectors = result.minisectors.filter((sector) => sector.midpoint.x != null && sector.midpoint.y != null && sector.winner_driver_code);
  const midpoints = sectors.map((sector) => ({ x: Number(sector.midpoint.x), y: Number(sector.midpoint.y) }));
  const bounds = sectors.length < 2 ? null : boundsOf(midpoints);
  if (!bounds) return <EmptyState title="Track map unavailable" detail="The minisector artifact has no usable coordinates." />;
  const projection = fitBounds(bounds, DOMINANCE_VIEWPORT);
  const placed = midpoints.map((midpoint) => project(projection, midpoint));
  const winners = [...new Set(sectors.map((sector) => sector.winner_driver_code).filter((winner): winner is string => Boolean(winner)))];
  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_220px]">
      <svg viewBox="0 0 600 400" className="min-h-[280px] w-full rounded-md border border-line/70 bg-carbon/50 p-3" role="img" aria-label="Track dominance by driver">
        {sectors.slice(1).map((sector, index) => {
          const from = placed[index];
          const to = placed[index + 1];
          const style = driverStyle(styles, sector.winner_driver_code || "");
          return (
            <line
              key={sector.index}
              x1={from.x}
              y1={from.y}
              x2={to.x}
              y2={to.y}
              stroke={style.color}
              strokeWidth="10"
              strokeLinecap={style.dash ? "butt" : "round"}
              strokeDasharray={style.dash ? TRACK_DASH : undefined}
            />
          );
        })}
      </svg>
      <div className="space-y-2">
        <div className="eyebrow mb-3">Minisectors won</div>
        {winners.map((winner) => {
          const count = sectors.filter((sector) => sector.winner_driver_code === winner).length;
          return (
            <div key={winner} className="flex items-center justify-between rounded-md border border-line/70 bg-carbon/40 p-3">
              <span className="inline-flex items-center gap-2 font-mono font-semibold text-white">
                <DriverMark style={driverStyle(styles, winner)} mark="line" />
                {winner}
              </span>
              <span className="font-mono text-sm font-bold text-white">{count}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function CarPerformanceView({ result, drivers }: { result: CarPerformanceResult; drivers: Driver[] }) {
  const colors = teamColorByDriver(drivers);
  return <DataTable rows={result.drivers} columns={[
    { key: "driver", header: "Driver", render: (row) => <DriverBadge code={row.driver_code || "--"} color={colors[row.driver_code || ""]} /> },
    { key: "max", header: "Max", align: "right", render: (row) => `${formatNumber(row.max_speed_kph, 0)} km/h` },
    { key: "low", header: "Low speed", align: "right", render: (row) => formatNumber(row.low_speed_avg_kph, 0) },
    { key: "medium", header: "Medium", align: "right", render: (row) => formatNumber(row.medium_speed_avg_kph, 0) },
    { key: "high", header: "High speed", align: "right", render: (row) => formatNumber(row.high_speed_avg_kph, 0) },
    { key: "throttle", header: "Full throttle", align: "right", render: (row) => `${formatNumber(row.full_throttle_pct, 1)}%` },
    { key: "braking", header: "Braking", align: "right", render: (row) => `${formatNumber(row.braking_pct, 1)}%` }
  ]} />;
}

function CornerAnalysisView({ result, drivers }: { result: CornerAnalysisResult; drivers: Driver[] }) {
  const colors = teamColorByDriver(drivers);
  const rows = result.corners.flatMap((corner) => corner.drivers.map((driver) => ({ ...driver, corner_number: corner.corner_number, distance_m: corner.distance_m })));
  return <DataTable rows={rows} columns={[
    { key: "corner", header: "Corner", render: (row) => `T${row.corner_number}` },
    { key: "driver", header: "Driver", render: (row) => <DriverBadge code={row.driver_code} color={colors[row.driver_code]} /> },
    { key: "brake", header: "Brake point", align: "right", render: (row) => `${formatNumber(row.brake_start_m, 0)} m` },
    { key: "distance", header: "Brake distance", align: "right", render: (row) => `${formatNumber(row.braking_distance_m, 0)} m` },
    { key: "entry", header: "Entry", align: "right", render: (row) => `${formatNumber(row.entry_speed_kph, 0)} km/h` },
    { key: "apex", header: "Apex", align: "right", render: (row) => `${formatNumber(row.apex_speed_kph, 0)} km/h` },
    { key: "exit", header: "Exit", align: "right", render: (row) => `${formatNumber(row.exit_speed_kph, 0)} km/h` }
  ]} />;
}

function PacePredictionView({ result, drivers }: { result: PacePredictionResult; drivers: Driver[] }) {
  const colors = teamColorByDriver(drivers);
  return <DataTable rows={result.drivers} columns={[
    { key: "driver", header: "Driver", render: (row) => <DriverBadge code={row.driver_code || "--"} color={colors[row.driver_code || ""]} /> },
    { key: "pace", header: "Est. pace", align: "right", render: (row) => formatMs(row.estimated_race_pace_ms) },
    { key: "gap", header: "Gap", align: "right", render: (row) => formatDelta(row.gap_to_best_ms) },
    { key: "runs", header: "Long runs", align: "right", render: (row) => row.stint_count ?? "--" },
    { key: "laps", header: "Laps", align: "right", render: (row) => row.sample_count ?? "--" },
    { key: "spread", header: "Variability", align: "right", render: (row) => formatDelta(row.variability_ms) },
    { key: "confidence", header: "Confidence", render: (row) => String(row.confidence ?? "--") }
  ]} />;
}

function AnalysisCaveats({ caveats }: { caveats?: string[] }) {
  if (!caveats?.length) return null;
  return <p className="mt-4 rounded-md border border-amber/20 bg-amber/5 p-3 text-xs leading-5 text-slate-400"><span className="font-bold text-amber">Method note: </span>{caveats.join(" ")}</p>;
}
