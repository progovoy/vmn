import { memo, useMemo, type ComponentProps } from "react";
import type { MetricChart } from "../types";
import { splitCharts } from "../util/metricDisplay";
import MetricGrid from "./MetricGrid";
import MetricBars from "./MetricBars";
import MetricTable from "./MetricTable";

/** MetricGrid, but the metrics *charts* hints `bars` or `table` (plan 28
 *  N8) are drawn that way, after the curves. */
function HintedMetricGrid({ charts, ...grid }: ComponentProps<typeof MetricGrid> & {
  charts?: Record<string, MetricChart>;
}) {
  const [lines, hinted] = useMemo(() => splitCharts(grid.metrics, charts), [grid.metrics, charts]);
  return (
    <>
      <MetricGrid {...grid} metrics={lines} />
      {hinted.length > 0 && (
        <div style={{
          display: "grid", gridTemplateColumns: `repeat(auto-fill, minmax(${grid.minWidth ?? 320}px, 1fr))`,
          gap: 16, marginTop: lines.length ? 16 : 0,
        }}>
          {hinted.map((m) => (charts![m] === "bars"
            ? <MetricBars key={m} name={m} points={grid.series[m] ?? []} color={grid.colorOf(m)} />
            : <MetricTable key={m} name={m} points={grid.series[m] ?? []} />))}
        </div>
      )}
    </>
  );
}

export default memo(HintedMetricGrid);
