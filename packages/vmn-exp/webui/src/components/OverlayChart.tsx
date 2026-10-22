import { memo, useCallback, useMemo } from "react";
import { runColor } from "../util";
import type { XMode } from "../util/chartData";
import type { CurveSeries } from "../util/curveOptions";
import { emaXY, toXY } from "../util/seriesArrays";
import { fetchSeriesBatch } from "../apiSeries";
import { useJoinedSeries } from "../hooks/useJoinedSeries";
import type { SeriesPoint } from "../types";
import { metricCurves } from "../pages/overlayCoverage";
import { AUTO_X, xMetricLabel, xMetricMap, type XMap } from "../util/xMetric";
import { OVERLAY_POINTS, useOverlaySeries, type OverlayData, type OverlayRunData } from "../pages/overlaySeries";
import CurveChart from "./CurveChart";
import LazyMount from "./LazyMount";

type Joined = Record<string, Record<string, SeriesPoint[]>>;

const CHART_H = 260;
const NO_RUNS: ReadonlySet<string> = new Set();

export interface OverlayChartProps {
  ws: string;
  app: string;
  /** Runs drawn on every chart, coloured by their position here. */
  verstrs: string[];
  /** One chart per metric key. */
  keys: string[];
  maxPoints?: number;
  /** The x metric choice: `AUTO_X`, "none" or a metric name. */
  x?: string;
  smoothing?: number;
  xMode?: XMode;
  logY?: boolean;
  hidden?: ReadonlySet<string>;
  focused?: string | null;
  /** The runs' series when the caller already loaded them (no fetch then). */
  data?: OverlayData | null;
}

/** Overlaid training curves of *verstrs*, one card per metric in *keys*,
 *  rendered from props alone: the runs' series come from *data* or the
 *  overlay query, joined on an x metric when *x* (or a declared step metric) asks. */
export default function OverlayChart({
  ws, app, verstrs, keys, maxPoints = OVERLAY_POINTS, x = AUTO_X, smoothing = 0,
  xMode = "step", logY = false, hidden = NO_RUNS, focused = null, data: given,
}: OverlayChartProps) {
  const fetched = useOverlaySeries(ws, app, given ? [] : verstrs, maxPoints).data;
  const data = given ?? fetched;
  const loaded = useMemo(() => data?.runs ?? [], [data]);
  const loadedKeys = useMemo(() => loaded.map((r) => r.key), [loaded]);
  const xMap = useMemo(
    () => xMetricMap(keys, xMode, x, data?.stepMetrics), [keys, xMode, x, data],
  );
  const fetchJoined = useCallback(
    (m: XMap) => fetchSeriesBatch(ws, app, loadedKeys, Object.keys(m), maxPoints, m).then((b) => b.series),
    [ws, app, loadedKeys, maxPoints],
  );
  const { data: joined, error } = useJoinedSeries<Joined>(xMap, fetchJoined, data);
  const colorOf = useMemo(() => {
    const idx = new Map(verstrs.map((v, i) => [v, i]));
    return (key: string) => runColor(idx.get(key) ?? 0);
  }, [verstrs]);

  if (!data) return null;
  return (
    <>
      {error && <div className="error">{error.message}</div>}
      {keys.map((metric) => (
        <div key={metric} className="card" style={{ marginBottom: 16 }}>
          <h2 className="section-title">{metric}</h2>
          <LazyMount height={CHART_H}>
            <MetricOverlay
              metric={metric} runs={loaded} colorOf={colorOf} xMode={xMode}
              xMetric={joined ? xMap[metric] ?? null : null} joined={joined}
              alpha={smoothing} logY={logY} hidden={hidden} focused={focused}
            />
          </LazyMount>
        </div>
      ))}
    </>
  );
}

/** One metric across the runs that logged it. Each run keeps its own typed
 *  x/y arrays, and "relative" x is measured from each run's own start. With
 *  many runs the smoothed curve replaces the raw one rather than doubling the
 *  lines. A run missing the x metric drops out of that chart only, and with
 *  no run joined the chart stays on the plain axis. */
const MetricOverlay = memo(function MetricOverlay({
  metric, runs, colorOf, xMode: plainMode, xMetric: wantedX, joined, alpha, logY, hidden, focused,
}: {
  metric: string;
  runs: OverlayRunData[];
  colorOf: (key: string) => string;
  xMode: XMode;
  /** Plot against this metric, from *joined*, instead of *xMode*. */
  xMetric: string | null;
  joined: Joined | null;
  alpha: number;
  logY: boolean;
  hidden: ReadonlySet<string>;
  focused: string | null;
}) {
  const { xMetric, curves } = useMemo(
    () => metricCurves(metric, runs, wantedX, joined), [metric, runs, wantedX, joined],
  );
  const xMode = xMetric ? "metric" : plainMode;
  const raw = useMemo(
    () => curves.map((c) => ({ key: c.key, ...toXY(c.points, xMode, c.origin, { positiveOnly: logY }) })),
    [curves, xMode, logY],
  );
  const formatX = useMemo(() => (xMetric ? xMetricLabel(xMetric) : undefined), [xMetric]);
  const series = useMemo<CurveSeries[]>(
    () => raw.map((r) => ({ ...r, label: r.key, color: colorOf(r.key), ys: emaXY(r.ys, alpha) })),
    [raw, colorOf, alpha],
  );
  // One point per run is a value, not a curve (curves need two points).
  const single = !curves.length && runs.some((r) => r.series[metric]?.length === 1);
  return (
    <CurveChart
      series={series} xMode={xMode} logY={logY} height={CHART_H}
      hidden={hidden} focused={focused} formatX={formatX}
      emptyText={single ? `${metric} has one value per run, not a curve: compare it on a scatter or in a table.` : undefined}
    />
  );
});
