import { memo, useMemo, useRef, useState } from "react";
import type uPlot from "uplot";
import type { XMode } from "../util/chartData";
import { chartTheme } from "../util/cssColor";
import { useThemeVersion } from "../hooks/useTheme";
import {
  curveData, curveOptions, X_TICK, type CurveSeries,
} from "../util/curveOptions";
import { tooltipRows } from "../util/seriesArrays";
import { withStepMarker } from "../util/chartMarkers";
import { isFullRange, type StepRange } from "../util/zoomSeries";
import CurveTooltip from "./CurveTooltip";
import UPlotChart, { type CursorInfo } from "./UPlotChart";

/** Tooltip rows shown at most — with 100 runs, the ones nearest the cursor. */
const DEFAULT_TOOLTIP_LIMIT = 8;

const stepLabel = (x: number) => `step ${x}`;

/** Canvas line chart (uPlot) of independent curves, each with its own x
 *  values. The plot is rebuilt only when the set of curves or the axis kind
 *  changes; new values for the same curves are swapped in place. */
function CurveChart({
  series, xMode, logY = false, height = 280, hidden, focused = null,
  tooltipLimit = DEFAULT_TOOLTIP_LIMIT, hideX = false, formatX, markX = null, onXRange,
}: {
  series: CurveSeries[];
  xMode: XMode;
  logY?: boolean;
  height?: number;
  /** Keys of curves switched off. */
  hidden?: ReadonlySet<string>;
  /** Key of the curve to highlight. */
  focused?: string | null;
  tooltipLimit?: number;
  hideX?: boolean;
  formatX?: (x: number) => string;
  /** Step axes only: mark this x with a dashed line (a fork point). */
  markX?: number | null;
  /** Step axes only: the visible x range after a drag-zoom, null once reset
   *  to the whole data. The zoom then survives new data. */
  onXRange?: (range: StepRange | null) => void;
}) {
  // Keyed on the curves' identity, not their arrays: fresh values for the
  // same curves (a poll) must not rebuild the plot.
  const shape = series.map((s) => `${s.key}|${s.color}|${s.faded ? 1 : 0}`).join(",");
  const themeVersion = useThemeVersion();
  const zoomable = xMode === "step" && Boolean(onXRange);
  const zoom = useXZoom(series, onXRange);
  const options = useMemo(() => {
    const theme = chartTheme();
    const opts = curveOptions(series, { xMode, logY, height, hideX, theme });
    const marked = withStepMarker(opts, xMode === "step" ? markX : null, theme.axis);
    return zoomable ? withScaleHook(marked, zoom.onScale) : marked;
  }, [shape, xMode, logY, height, hideX, themeVersion, markX, zoomable]);
  const data = useMemo(() => curveData(series), [series]);
  const hiddenFlags = useMemo(() => hidden && series.map((s) => hidden.has(s.key)), [shape, hidden]);
  const focusIdx = focused === null ? -1 : series.findIndex((s) => s.key === focused && !s.faded);
  const focus = focusIdx >= 0 ? focusIdx : null;

  const [cursor, setCursor] = useState<CursorInfo | null>(null);
  const visible = useMemo(
    () => series.filter((s) => !s.faded && !hidden?.has(s.key)), [series, hidden],
  );
  const rows = useMemo(
    () => (cursor ? tooltipRows(visible, cursor.x, cursor.y, tooltipLimit) : []),
    [cursor, visible, tooltipLimit],
  );
  const wrapRef = useRef<HTMLDivElement>(null);

  return (
    <div data-testid="curve-chart" ref={wrapRef} style={{ position: "relative", width: "100%" }}>
      <UPlotChart
        options={options}
        data={data}
        hidden={hiddenFlags}
        focus={focus}
        onCursor={setCursor}
        keepX={zoomable ? zoom.range : undefined}
      />
      {cursor && rows.length > 0 && (
        <CurveTooltip
          rows={rows}
          series={visible}
          cursor={cursor}
          width={wrapRef.current?.clientWidth ?? 0}
          formatX={formatX ?? X_TICK[xMode] ?? stepLabel}
        />
      )}
    </div>
  );
}

type Options = ReturnType<typeof curveOptions>;

function withScaleHook(opts: Options, onScale: (u: uPlot, key: string) => void): Options {
  const hooks = opts.hooks ?? {};
  return { ...opts, hooks: { ...hooks, setScale: [...(hooks.setScale ?? []), onScale] } };
}

function extentOf(series: CurveSeries[]): StepRange {
  let lo = Infinity;
  let hi = -Infinity;
  for (const s of series) {
    for (const x of s.xs) {
      if (x < lo) lo = x;
      if (x > hi) hi = x;
    }
  }
  return [lo, hi];
}

/** Tracks the zoomed x range (null: whole data) from uPlot's setScale hook
 *  and reports changes to *onXRange*. */
function useXZoom(series: CurveSeries[], onXRange?: (range: StepRange | null) => void) {
  const range = useRef<StepRange | null>(null);
  const extent = useRef<StepRange>([0, 0]);
  extent.current = useMemo(() => extentOf(series), [series]);
  const report = useRef(onXRange);
  report.current = onXRange;
  const onScale = useMemo(() => (u: uPlot, key: string) => {
    const { min, max } = u.scales[key] ?? {};
    if (key !== "x" || min == null || max == null) return;
    const next: StepRange | null = isFullRange([min, max], extent.current) ? null : [min, max];
    range.current = next;
    report.current?.(next);
  }, []);
  return { range, onScale };
}

export default memo(CurveChart);
