import { memo, useMemo } from "react";
import type { SeriesPoint } from "../types";
import type { XMode } from "../util/chartData";
import { withSmoothing } from "../util/curveOptions";
import { toXY } from "../util/seriesArrays";
import { chartPoints, xMetricLabel, type XMap } from "../util/xMetric";
import { spliceZoom } from "../util/zoomSeries";
import { useZoomRefetch, type FetchRange } from "../hooks/useZoomRefetch";
import CurveChart from "./CurveChart";
import LazyMount from "./LazyMount";

const HEADER_H = 22;

export interface GridView {
  xMode: XMode;
  origin: number;
  alpha: number;
  logY: boolean;
  /** Mark this step on step charts (where a forked run branched off). */
  markStep?: number | null;
}

const MetricCell = memo(function MetricCell({
  name, points: coarse, xMetric, color, view, height, fetchRange,
}: {
  name: string;
  points: SeriesPoint[];
  /** Plot against this metric (the points carry `x`) instead of the step. */
  xMetric: string | null;
  color: string;
  view: GridView;
  height: number;
  /** Refetches a drag-zoomed step range at full resolution. */
  fetchRange?: FetchRange;
}) {
  const { origin, alpha, logY } = view;
  const xMode = xMetric ? "metric" : view.xMode;
  const zoomable = xMode === "step" && Boolean(fetchRange);
  const { zoom, onXRange } = useZoomRefetch(name, zoomable ? fetchRange : undefined);
  const points = useMemo(() => (zoomable ? spliceZoom(coarse, zoom) : coarse), [coarse, zoom, zoomable]);
  const markStep = xMode === "step" ? view.markStep ?? null : null;
  const formatX = useMemo(() => (xMetric ? xMetricLabel(xMetric) : undefined), [xMetric]);
  const curves = useMemo(() => {
    const xy = toXY(points, xMode, origin, { positiveOnly: logY });
    return withSmoothing({ key: name, label: name, color, ...xy }, alpha);
  }, [points, xMode, origin, logY, alpha, name, color]);
  return (
    <div data-testid="metric-chart" data-metric={name} data-mark-step={markStep ?? undefined}>
      <div className="mono" style={{ fontSize: 12, color: "var(--text-2)", height: HEADER_H }}>
        {name}{xMetric && <span style={{ color: "var(--text-3)" }}> vs {xMetric}</span>}
      </div>
      <LazyMount height={height}>
        <CurveChart
          series={curves} xMode={xMode} logY={logY} height={height} formatX={formatX} markX={markStep}
          onXRange={zoomable ? onXRange : undefined}
        />
      </LazyMount>
    </div>
  );
});

const NO_JOINS: XMap = {};

/** Small multiples: one chart per metric, each on its own y scale, mounted
 *  only once scrolled into view. Metrics of *xMap* are drawn from *joined*
 *  against their x metric once it has arrived. */
function MetricGrid({
  metrics, series, colorOf, view, height = 180, minWidth = 320, joined = null, xMap = NO_JOINS,
  fetchRange,
}: {
  metrics: string[];
  series: Record<string, SeriesPoint[]>;
  joined?: Record<string, SeriesPoint[]> | null;
  xMap?: XMap;
  colorOf: (metric: string) => string;
  view: GridView;
  height?: number;
  minWidth?: number;
  fetchRange?: FetchRange;
}) {
  return (
    <div style={{
      display: "grid", gridTemplateColumns: `repeat(auto-fill, minmax(${minWidth}px, 1fr))`, gap: 16,
    }}>
      {metrics.map((m) => {
        const { points, xMetric } = chartPoints(series, joined, m, xMap);
        return (
          <MetricCell
            key={m} name={m} points={points} xMetric={xMetric}
            color={colorOf(m)} view={view} height={height} fetchRange={fetchRange}
          />
        );
      })}
    </div>
  );
}

export default memo(MetricGrid);
