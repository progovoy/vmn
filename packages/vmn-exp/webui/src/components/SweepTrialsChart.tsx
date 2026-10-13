/** A sweep's trials as parallel coordinates (plan 20 B6): the sweep metric
 *  and the params that vary among the trials, coloured toward the goal. */
import { lazy, Suspense, useMemo } from "react";
import type { ExperimentRow, MetricsSchema } from "../types";
import type { FleetRow, Goal } from "./fleetRows";

const ParallelCoordinates = lazy(() => import("./ParallelCoordinates"));

export default function SweepTrialsChart({ rows, paramKeys, metric }: {
  rows: FleetRow[];
  paramKeys: string[];
  metric: { name: string; goal: Goal };
}) {
  const chartRows = useMemo(() => rows.map((r) => ({
    verstr: r.verstr, params: r.params, metrics: { [metric.name]: r.value },
  }) as unknown as ExperimentRow), [rows, metric.name]);
  const schema = useMemo<MetricsSchema>(
    () => ({ [metric.name]: { primary: true, ...(metric.goal ? { goal: metric.goal } : {}) } }),
    [metric.name, metric.goal],
  );
  const metricCols = useMemo(() => [metric.name], [metric.name]);
  if (rows.length < 2) return null;
  return (
    <section aria-label="Trials in parallel coordinates" style={{ marginTop: 12 }}>
      <Suspense fallback={null}>
        <ParallelCoordinates rows={chartRows} metricCols={metricCols} paramCols={paramKeys} schema={schema} />
      </Suspense>
    </section>
  );
}
