import { lazy, Suspense } from "react";
import type { ExperimentRow, MetricsSchema } from "../types";
import type { RowsFilter } from "../queries";
import { CHART_VIEWS, type ChartView } from "../hooks/useLeaderboardView";
import Segmented from "../components/Segmented";
import AddToReport from "../reports/AddToReport";
import { leaderboardSpec } from "../reports/viewSpecs";
import ChartGroupLegend from "../components/ChartGroupLegend";
import type { ChartGroups } from "../util/chartGroups";

// Chart code is heavy (uPlot among it); loading them lazily keeps them off the table's
// critical path — the rows paint while the chart code is still arriving.
const ParamPlots = lazy(() => import("../components/ParamPlots"));
const MetricBarChart = lazy(() => import("../components/MetricBarChart"));
const MetricScatter = lazy(() => import("../components/MetricScatter"));
const ParallelCoordinates = lazy(() => import("../components/ParallelCoordinates"));
const GroupedMetrics = lazy(() => import("../components/GroupedMetrics"));
const ParamImportance = lazy(() => import("../components/ParamImportance"));

const LABELS: Record<ChartView, string> = {
  trend: "Trend", bar: "Bar", scatter: "Scatter", parallel: "Parallel", grouped: "Grouped",
  importance: "Importance",
};
const VIEW_OPTIONS = CHART_VIEWS.map((v) => [v, LABELS[v]] as const);

/** What the importance panel asks the server about: the board's app and filter. */
export interface ImportanceSource {
  ws: string;
  app: string;
  filter: RowsFilter;
  defaultMetric?: string | null;
}

/** What the selection does to the chart (hooks/useChartSelection). */
export interface ChartSelection {
  selectedCount: number | null;
  showingAll: boolean;
  setShowAll: (all: boolean) => void;
}

/** `Showing N selected · Show all`, or the coverage *label* with a way back
 *  to the selection. */
function Coverage({ label, selection }: { label?: string; selection?: ChartSelection }) {
  const count = selection?.selectedCount ?? null;
  if (count === null || !selection) return label ? <span className="chart-coverage">{label}</span> : null;
  if (selection.showingAll) {
    return (
      <span className="chart-coverage">
        {label && <><span>{label}</span>{" · "}</>}
        <button type="button" className="link" onClick={() => selection.setShowAll(false)}>Show {count} selected</button>
      </span>
    );
  }
  return (
    <span className="chart-coverage">
      <span>Showing {count} selected</span>{" · "}
      <button type="button" className="link" onClick={() => selection.setShowAll(true)}>Show all</button>
    </span>
  );
}

export function ChartFallback() {
  return <div className="chart-fallback" aria-label="loading chart" />;
}

export default function LeaderboardCharts({
  view, onView, rows, label, metricCols, paramCols, schema, onBrush, importance, groups, selection,
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
  importance: ImportanceSource;
  /** Each run's group colour on a grouped board (plan 22 G7). */
  groups?: ChartGroups;
  /** Set when the charts follow the board's selection (plan 22 F7). */
  selection?: ChartSelection;
}) {
  const common = { rows, metricCols, schema };
  const spec = () => leaderboardSpec({
    app: importance.app, view, filter: importance.filter, verstrs: rows.map((r) => r.verstr),
    metricCols, paramCols, defaultMetric: importance.defaultMetric,
  });
  return (
    <>
      <div className="chart-views">
        <Segmented label="Chart type" options={VIEW_OPTIONS} value={view} onChange={onView} />
        <Coverage label={label} selection={selection} />
        <span style={{ marginLeft: "auto" }}><AddToReport ws={importance.ws} spec={spec} /></span>
      </div>
      {groups && <ChartGroupLegend legend={groups.legend} />}
      <Suspense fallback={<ChartFallback />}>
        {view === "trend" && <ParamPlots {...common} />}
        {view === "bar" && <MetricBarChart {...common} groups={groups} />}
        {view === "scatter" && <MetricScatter {...common} paramCols={paramCols} groups={groups} />}
        {view === "parallel" && <ParallelCoordinates {...common} paramCols={paramCols} onBrush={onBrush} groups={groups} />}
        {view === "grouped" && <GroupedMetrics {...common} paramCols={paramCols} />}
        {view === "importance" && <ParamImportance {...common} {...importance} paramCols={paramCols} />}
      </Suspense>
    </>
  );
}
