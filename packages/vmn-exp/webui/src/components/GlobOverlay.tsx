import { memo, useMemo } from "react";
import type { SeriesPoint } from "../types";
import { seriesColor } from "../util";
import { withSmoothing } from "../util/curveOptions";
import { matchKeys } from "../util/metricGlob";
import { toXY } from "../util/seriesArrays";
import CurveChart from "./CurveChart";
import type { GridView } from "./MetricGrid";

/** Curves one overlay chart draws at most. */
export const MAX_OVERLAY_SERIES = 20;

const CHART_H = 260;

/** The Run page overlay: every metric of *names* the fnmatch *pattern*
 *  matches (`cv*.grad_norm_mean`, the matcher `define_metric` uses), in one
 *  chart on one y axis — log y follows *view* — up to MAX_OVERLAY_SERIES,
 *  with a note when more match. A metric x axis falls back to the step. */
function GlobOverlay({ pattern, names, series, view }: {
  pattern: string;
  names: string[];
  series: Record<string, SeriesPoint[]>;
  view: GridView;
}) {
  const matched = useMemo(() => matchKeys(pattern, names), [pattern, names]);
  const keys = useMemo(() => matched.slice(0, MAX_OVERLAY_SERIES), [matched]);
  const xMode = view.xMode === "metric" ? "step" : view.xMode;
  const step = xMode === "step";
  const curves = useMemo(() => keys.flatMap((k) => withSmoothing({
    key: k, label: k, color: seriesColor(keys, k),
    ...toXY(series[k] ?? [], xMode, view.origin, { positiveOnly: view.logY }),
  }, view.alpha)), [keys, series, xMode, view.origin, view.logY, view.alpha]);

  if (!matched.length) {
    return <div style={{ color: "var(--text-3)", fontSize: 12, marginBottom: 12 }}>No metric matches the overlay “{pattern}”.</div>;
  }
  return (
    <div data-testid="overlay-chart" data-keys={keys.join(",")} style={{ marginBottom: 16 }}>
      <div className="mono" style={{ fontSize: 12, color: "var(--text-2)", marginBottom: 4 }}>
        {pattern} · {keys.length} metrics
        {matched.length > keys.length && (
          <span style={{ color: "var(--text-3)" }}> · <span>showing {keys.length} of {matched.length} matches</span></span>
        )}
      </div>
      <CurveChart
        series={curves} xMode={xMode} logY={view.logY} height={CHART_H} tooltipLimit={MAX_OVERLAY_SERIES}
        markX={step ? view.markStep ?? null : null} bands={step ? view.ranges ?? null : null}
      />
    </div>
  );
}

export default memo(GlobOverlay);
