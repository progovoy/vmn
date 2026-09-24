import { lazy, Suspense } from "react";
import type { ExperimentRow, MetricsSchema } from "../types";
import { CHART_VIEWS, type ChartView } from "../hooks/useLeaderboardView";

// Charts pull in recharts; loading them lazily keeps them off the table's
// critical path — the rows paint while the chart code is still arriving.
const ParamPlots = lazy(() => import("../components/ParamPlots"));
const MetricBarChart = lazy(() => import("../components/MetricBarChart"));
const MetricScatter = lazy(() => import("../components/MetricScatter"));
const ParallelCoordinates = lazy(() => import("../components/ParallelCoordinates"));
const GroupedMetrics = lazy(() => import("../components/GroupedMetrics"));

const LABELS: Record<ChartView, string> = {
  trend: "Trend", bar: "Bar", scatter: "Scatter", parallel: "Parallel", grouped: "Grouped",
};

export function ChartFallback() {
  return <div className="chart-fallback" aria-label="loading chart" />;
}

export default function LeaderboardCharts({
  view, onView, rows, label, metricCols, paramCols, schema, onBrush,
}: {
  view: ChartView;
  onView: (v: ChartView) => void;
  rows: ExperimentRow[];
  /** How much of the filtered set the chart covers. */
  label?: string;
  metricCols: string[];
  paramCols: string[];
  schema: MetricsSchema | null;
  onBrush: (indices: number[] | null) => void;
}) {
  const common = { rows, metricCols, schema };
  return (
    <>
      <div style={{ display: "flex", gap: 8, marginBottom: 8, alignItems: "center" }}>
        {CHART_VIEWS.map((v) => (
          <button
            key={v} className={view === v ? "primary" : ""}
            aria-pressed={view === v} onClick={() => onView(v)}
          >
            {LABELS[v]}
          </button>
        ))}
        {label && <span className="chart-coverage">{label}</span>}
      </div>
      <Suspense fallback={<ChartFallback />}>
        {view === "trend" && <ParamPlots {...common} />}
        {view === "bar" && <MetricBarChart {...common} />}
        {view === "scatter" && <MetricScatter {...common} paramCols={paramCols} />}
        {view === "parallel" && <ParallelCoordinates {...common} paramCols={paramCols} onBrush={onBrush} />}
        {view === "grouped" && <GroupedMetrics {...common} paramCols={paramCols} />}
      </Suspense>
    </>
  );
}
