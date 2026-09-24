import { memo, useMemo } from "react";
import type { SeriesPoint } from "../types";
import type { XMode } from "../util/chartData";
import { withSmoothing } from "../util/curveOptions";
import { toXY } from "../util/seriesArrays";
import CurveChart from "./CurveChart";
import LazyMount from "./LazyMount";

const HEADER_H = 22;

export interface GridView {
  xMode: XMode;
  origin: number;
  alpha: number;
  logY: boolean;
}

const MetricCell = memo(function MetricCell({ name, points, color, view, height }: {
  name: string;
  points: SeriesPoint[];
  color: string;
  view: GridView;
  height: number;
}) {
  const { xMode, origin, alpha, logY } = view;
  const curves = useMemo(() => {
    const xy = toXY(points, xMode, origin, { positiveOnly: logY });
    return withSmoothing({ key: name, label: name, color, ...xy }, alpha);
  }, [points, xMode, origin, logY, alpha, name, color]);
  return (
    <div data-testid="metric-chart" data-metric={name}>
      <div className="mono" style={{ fontSize: 12, color: "var(--text-2)", height: HEADER_H }}>{name}</div>
      <LazyMount height={height}>
        <CurveChart series={curves} xMode={xMode} logY={logY} height={height} />
      </LazyMount>
    </div>
  );
});

/** Small multiples: one chart per metric, each on its own y scale, mounted
 *  only once scrolled into view. */
function MetricGrid({ metrics, series, colorOf, view, height = 180, minWidth = 320 }: {
  metrics: string[];
  series: Record<string, SeriesPoint[]>;
  colorOf: (metric: string) => string;
  view: GridView;
  height?: number;
  minWidth?: number;
}) {
  return (
    <div style={{
      display: "grid", gridTemplateColumns: `repeat(auto-fill, minmax(${minWidth}px, 1fr))`, gap: 16,
    }}>
      {metrics.map((m) => (
        <MetricCell key={m} name={m} points={series[m] ?? []} color={colorOf(m)} view={view} height={height} />
      ))}
    </div>
  );
}

export default memo(MetricGrid);
