import { memo, useMemo, useState } from "react";
import type { SeriesPoint } from "../types";
import { fmtVal } from "../util";
import { barStats, byValue, lastPerStep, type StepValue } from "../util/metricDisplay";

/** Tall enough for a dozen bars; more scroll. */
const MAX_HEIGHT = 260;

function mean(rows: StepValue[]): number {
  const finite = rows.map((r) => r.value).filter(Number.isFinite);
  return finite.length ? finite.reduce((a, b) => a + b, 0) / finite.length : 0;
}

/** A `chart: bars` metric (plan 28 N8): the last value per step as bars,
 *  largest first — the step is each bar's label, not an axis — with the
 *  max and the share over a threshold (the mean until one is typed). */
function MetricBars({ name, points, color }: {
  name: string; points: SeriesPoint[]; color: string;
}) {
  const rows = useMemo(() => byValue(lastPerStep(points)), [points]);
  const [typed, setTyped] = useState("");
  const threshold = typed.trim() !== "" && Number.isFinite(Number(typed)) ? Number(typed) : mean(rows);
  const stats = barStats(rows, threshold);
  const scale = Math.max(...rows.map((r) => Math.abs(r.value)).filter(Number.isFinite), 0) || 1;
  return (
    <div data-testid="metric-bars" data-metric={name}>
      <div className="mono" style={{ fontSize: 12, color: "var(--text-2)" }}>{name}</div>
      <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap", fontSize: 11, color: "var(--text-3)", margin: "4px 0" }}>
        <span>max {fmtVal(stats.max)}</span>
        <span>
          {stats.over} of {stats.total}
          {stats.share !== null && ` (${Math.round(stats.share * 100)}%)`} &gt; {fmtVal(threshold)}
        </span>
        <input
          aria-label="threshold" type="number" step="any" value={typed} placeholder="threshold"
          onChange={(e) => setTyped(e.target.value)} style={{ width: 90, fontSize: 11 }}
        />
      </div>
      <div style={{ maxHeight: MAX_HEIGHT, overflowY: "auto" }}>
        {rows.map((r) => (
          <div key={String(r.step)} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11, height: 18 }}>
            <span data-testid="bar-step" className="mono" style={{ width: 48, textAlign: "right", color: "var(--text-3)" }}>
              {r.step ?? "–"}
            </span>
            <span style={{ flex: 1, minWidth: 0 }}>
              <span style={{
                display: "block", height: 12, background: color,
                opacity: r.value > threshold ? 1 : 0.45,
                width: Number.isFinite(r.value) ? `${(Math.abs(r.value) / scale) * 100}%` : 0,
              }} />
            </span>
            <span className="mono" style={{ width: 64 }}>{fmtVal(Number.isFinite(r.value) ? r.value : null)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default memo(MetricBars);
