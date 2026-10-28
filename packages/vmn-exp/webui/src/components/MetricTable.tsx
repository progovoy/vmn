import { memo, useMemo } from "react";
import type { SeriesPoint } from "../types";
import { fmtVal } from "../util";
import { lastPerStep } from "../util/metricDisplay";

const MAX_HEIGHT = 260;

/** A `chart: table` metric (plan 28 N8): step -> the last value logged there. */
function MetricTable({ name, points }: { name: string; points: SeriesPoint[] }) {
  const rows = useMemo(() => lastPerStep(points), [points]);
  return (
    <div data-testid="metric-table" data-metric={name}>
      <div className="mono" style={{ fontSize: 12, color: "var(--text-2)" }}>{name}</div>
      <div style={{ maxHeight: MAX_HEIGHT, overflowY: "auto" }}>
        <table className="mono" style={{ fontSize: 11, borderCollapse: "collapse", width: "100%" }}>
          <thead>
            <tr><th style={{ textAlign: "left" }}>step</th><th style={{ textAlign: "left" }}>value</th></tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={String(r.step)}>
                <td>{r.step ?? "–"}</td>
                <td>{fmtVal(Number.isFinite(r.value) ? r.value : null)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default memo(MetricTable);
