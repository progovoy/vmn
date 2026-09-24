import { memo, useCallback, useMemo, useRef, useState } from "react";
import type { XMode } from "../util/chartData";
import { chartTheme } from "../util/cssColor";
import {
  curveData, curveOptions, fmtRelTick, fmtWallTick, type CurveSeries,
} from "../util/curveOptions";
import { tooltipRows } from "../util/seriesArrays";
import CurveTooltip from "./CurveTooltip";
import UPlotChart, { type CursorInfo } from "./UPlotChart";

export { fmtRelTick, fmtWallTick };

/** Tooltip rows shown at most — with 100 runs, the ones nearest the cursor. */
const DEFAULT_TOOLTIP_LIMIT = 8;

const defaultFormatX = (mode: XMode) => (x: number) =>
  mode === "wall" ? fmtWallTick(x) : mode === "relative" ? fmtRelTick(x) : `step ${x}`;

/** Canvas line chart (uPlot) of independent curves, each with its own x
 *  values. The plot is rebuilt only when the set of curves or the axis kind
 *  changes; new values for the same curves are swapped in place. */
function CurveChart({
  series, xMode, logY = false, height = 280, hidden, focused = null,
  tooltipLimit = DEFAULT_TOOLTIP_LIMIT, hideX = false, formatX,
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
}) {
  // Keyed on the curves' identity, not their arrays: fresh values for the
  // same curves (a poll) must not rebuild the plot.
  const shape = series.map((s) => `${s.key}|${s.color}|${s.faded ? 1 : 0}`).join(",");
  const options = useMemo(
    () => curveOptions(series, { xMode, logY, height, hideX, theme: chartTheme() }),
    [shape, xMode, logY, height, hideX],
  );
  const data = useMemo(() => curveData(series), [series]);
  const hiddenFlags = useMemo(() => hidden && series.map((s) => hidden.has(s.key)), [shape, hidden]);
  const focusIdx = focused === null ? -1 : series.findIndex((s) => s.key === focused && !s.faded);

  const [cursor, setCursor] = useState<CursorInfo | null>(null);
  const onCursor = useCallback((c: CursorInfo | null) => setCursor(c), []);
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
        focus={focusIdx >= 0 ? focusIdx : null}
        onCursor={onCursor}
      />
      {cursor && rows.length > 0 && (
        <CurveTooltip
          rows={rows}
          series={visible}
          cursor={cursor}
          width={wrapRef.current?.clientWidth ?? 0}
          formatX={formatX ?? defaultFormatX(xMode)}
        />
      )}
    </div>
  );
}

export default memo(CurveChart);
