import { useCallback, useEffect, useMemo, useRef } from "react";
import type { RowsFilter } from "../queries";
import type { ExperimentRow, MetricsSchema } from "../types";
import type { ChartView } from "../hooks/useLeaderboardView";
import { useChartRows } from "../hooks/useChartRows";
import LeaderboardCharts from "./LeaderboardCharts";

/** The Charts tab: what the charts plot and the brush they report. Mounted
 *  only while the tab is open, so the Runs tab fetches no chart data. */
export default function LeaderboardChartsPanel({
  ws, app, filter, view, onView, loaded, total, metricCols, paramCols, allParams, schema,
  defaultMetric, onBrushed,
}: {
  ws: string;
  app: string;
  filter: RowsFilter;
  view: ChartView;
  onView: (v: ChartView) => void;
  /** The rows the table has loaded, of *total* matching. */
  loaded: ExperimentRow[];
  total: number;
  metricCols: string[];
  paramCols: string[];
  /** Every param, hidden ones too (importance ranks them all). */
  allParams?: readonly string[];
  schema: MetricsSchema | null;
  defaultMetric?: string | null;
  /** The runs a parallel brush keeps (null: no brush). */
  onBrushed: (verstrs: Set<string> | null) => void;
}) {
  // Importance ranks every param, hidden ones too, so its drill-down needs them all.
  const chartParams = useMemo(
    () => (view === "importance" && allParams ? [...allParams] : paramCols),
    [view, allParams, paramCols],
  );
  const chart = useChartRows(ws, app, filter, view, metricCols, chartParams, loaded, total);
  // The chart keeps every row so its brush indices stay meaningful.
  const onBrush = useCallback(
    (indices: number[] | null) => onBrushed(indices
      ? new Set(indices.map((i) => chart.rows[i]?.verstr).filter((v): v is string => !!v))
      : null),
    [chart.rows, onBrushed],
  );
  // A brush leaves with its chart.
  const latest = useRef(onBrushed);
  latest.current = onBrushed;
  useEffect(() => () => latest.current(null), []);

  return (
    <LeaderboardCharts
      view={view} onView={onView} rows={chart.rows} label={chart.label}
      metricCols={metricCols} paramCols={chartParams} schema={schema} onBrush={onBrush}
      importance={{ ws, app, filter, defaultMetric }}
    />
  );
}
