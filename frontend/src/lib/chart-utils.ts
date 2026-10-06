import type { ChartSeries, TelemetryComparison } from "@/types/domain";

/** The Recharts tooltip box, shared so the charts cannot drift apart. */
export const CHART_TOOLTIP_STYLE = { background: "#111722", border: "1px solid #283246", color: "#e5edf8" };

/** Rows grouped by driver, in the order each driver first appears. */
export function groupByDriver<T extends { driver_code: string }>(rows: ReadonlyArray<T>): Array<[string, T[]]> {
  const groups = new Map<string, T[]>();
  for (const row of rows) {
    const group = groups.get(row.driver_code);
    if (group) {
      group.push(row);
    } else {
      groups.set(row.driver_code, [row]);
    }
  }
  return Array.from(groups.entries());
}

export function seriesToRows(series: ChartSeries[]): Array<Record<string, number | string | null>> {
  const lapNumbers = new Set<string | number>();
  // One lookup table per series keeps the pivot linear in the number of points
  // instead of scanning every series for every lap.
  const indexed = series.map((item) => {
    const byX = new Map<string | number, number | string | null>();
    item.x.forEach((x, index) => {
      lapNumbers.add(x);
      if (!byX.has(x)) {
        byX.set(x, item.y[index] ?? null);
      }
    });
    return { name: item.name, byX };
  });
  return Array.from(lapNumbers)
    .sort((a, b) => Number(a) - Number(b))
    .map((lap) => {
      const row: Record<string, number | string | null> = { lap };
      indexed.forEach((item) => {
        row[item.name] = item.byX.get(lap) ?? null;
      });
      return row;
    });
}

export function telemetryRows(compare: TelemetryComparison) {
  return compare.distance_m.map((distance, index) => ({
    distance,
    speedA: compare.speed_a[index],
    speedB: compare.speed_b[index],
    throttleA: compare.throttle_a[index],
    throttleB: compare.throttle_b[index],
    brakeA: compare.brake_a[index],
    brakeB: compare.brake_b[index],
    rpmA: compare.rpm_a[index],
    rpmB: compare.rpm_b[index],
    gearA: compare.gear_a[index],
    gearB: compare.gear_b[index],
    drsA: compare.drs_a[index],
    drsB: compare.drs_b[index],
    delta: compare.delta_speed_kph[index],
    deltaTime: compare.delta_time_ms?.[index] ?? null
  }));
}

