import { memo, useMemo, type ComponentProps } from "react";
import type { MetricChart, MetricSteps } from "../types";
import { splitCharts, stepRows } from "../util/metricDisplay";
import MetricGrid from "./MetricGrid";
import MetricBars from "./MetricBars";
import MetricTable from "./MetricTable";

/** MetricGrid, but the metrics *charts* hints `bars` or `table` (plan 28
 *  N8) are drawn that way, after the curves — from the server's unthinned
 *  *steps* when given (the grid's series are thinned). */
function HintedMetricGrid({ charts, steps, ...grid }: ComponentProps<typeof MetricGrid> & {
  charts?: Record<string, MetricChart>;
  steps?: Record<string, MetricSteps>;
}) {
  const [lines, hinted] = useMemo(() => splitCharts(grid.metrics, charts), [grid.metrics, charts]);
  const rowsOf = useMemo(
    () => new Map(hinted.map((m) => [m, stepRows(steps?.[m], grid.series[m] ?? [])])),
    [hinted, steps, grid.series],
  );
  return (
    <>
      <MetricGrid {...grid} metrics={lines} />
      {hinted.length > 0 && (
        <div style={{
          display: "grid", gridTemplateColumns: `repeat(auto-fill, minmax(${grid.minWidth ?? 320}px, 1fr))`,
          gap: 16, marginTop: lines.length ? 16 : 0,
        }}>
          {hinted.map((m) => {
            const rows = rowsOf.get(m)!;
            const total = steps?.[m]?.total ?? rows.length;
            return charts![m] === "bars"
              ? <MetricBars key={m} name={m} rows={rows} total={total} color={grid.colorOf(m)} />
              : <MetricTable key={m} name={m} rows={rows} total={total} />;
          })}
        </div>
      )}
    </>
  );
}

export default memo(HintedMetricGrid);
