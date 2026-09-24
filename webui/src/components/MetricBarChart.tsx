import { memo, useMemo, useState } from "react";
import type { ExperimentRow, MetricsSchema } from "../types";
import { fmtVal, metricGoal } from "../util";
import { isFiniteNumber } from "../util/stats";
import { useRunSelect } from "./chartHooks";

/** One bar per run stops being readable (and renderable) long before 50k runs. */
export const MAX_BARS = 50;

interface BarDatum { label: string; value: number; verstr: string }

/** Bar length as a percentage of the largest magnitude (negatives too). */
function widthPct(value: number, maxAbs: number): string {
  return `${maxAbs > 0 ? (Math.abs(value) / maxAbs) * 100 : 0}%`;
}

function Bar({ d, maxAbs, isBest, onClick }: {
  d: BarDatum; maxAbs: number; isBest: boolean; onClick: () => void;
}) {
  return (
    <button
      data-testid="bar"
      className="link"
      title={`${d.verstr}: ${fmtVal(d.value)}`}
      onClick={onClick}
      style={{ display: "grid", gridTemplateColumns: "50px 1fr 64px", alignItems: "center", gap: 8, width: "100%", padding: "2px 0" }}
    >
      <span className="mono" style={{ fontSize: 10, color: "var(--text-3)", textAlign: "right" }}>{d.label}</span>
      <span style={{ height: 16, background: "var(--panel-3)", borderRadius: 4, overflow: "hidden" }}>
        <span
          data-testid="bar-fill"
          style={{
            display: "block", height: "100%", borderRadius: "0 4px 4px 0",
            width: widthPct(d.value, maxAbs),
            background: isBest ? "var(--good)" : "var(--accent)",
            opacity: isBest ? 1 : 0.6,
          }}
        />
      </span>
      <span className="mono" style={{ fontSize: 10, color: "var(--text-2)" }}>{fmtVal(d.value)}</span>
    </button>
  );
}

/** The top runs by one metric, best first, as plain HTML bars that fill any
 *  width. Click a bar to open its run. */
function MetricBarChart({ rows, metricCols, schema, onSelect }: {
  rows: ExperimentRow[];
  metricCols: string[];
  schema: MetricsSchema | null;
  /** Called with a clicked bar's run; defaults to opening the run page. */
  onSelect?: (verstr: string) => void;
}) {
  const [metric, setMetric] = useState(metricCols[0] ?? "");
  const select = useRunSelect(onSelect);
  const goal = metricGoal(schema, metric);

  const { data, total, maxAbs } = useMemo(() => {
    const all = rows
      .map((r) => ({ label: `@${r.idx}`, value: r.metrics[metric], verstr: r.verstr }))
      .filter((d): d is BarDatum => isFiniteNumber(d.value));
    const best = [...all].sort((a, b) => (goal === "min" ? a.value - b.value : b.value - a.value));
    const shown = best.slice(0, MAX_BARS);
    return { data: shown, total: all.length, maxAbs: Math.max(0, ...shown.map((d) => Math.abs(d.value))) };
  }, [rows, metric, goal]);

  // `data` is sorted best-first, so the best value is its head.
  const best = data.length ? data[0].value : null;

  return (
    <div className="card">
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
        <div className="eyebrow" style={{ marginBottom: 0 }}>metric bar chart</div>
        <select
          role="combobox"
          value={metric}
          onChange={(e) => setMetric(e.target.value)}
          style={{ minWidth: 100 }}
        >
          {metricCols.map((m) => (
            <option key={m} value={m}>{m}</option>
          ))}
        </select>
      </div>
      {total > data.length && (
        <div style={{ color: "var(--text-3)", fontSize: 11, marginBottom: 6 }}>
          showing the top {MAX_BARS} of {total} runs by {metric}
        </div>
      )}
      <div data-testid="bar-chart" style={{ width: "100%", minHeight: 40 }}>
        {data.length === 0 && (
          <div style={{ color: "var(--text-3)", fontSize: 12 }}>No finite values for {metric}.</div>
        )}
        {data.map((d) => (
          <Bar key={d.verstr} d={d} maxAbs={maxAbs} isBest={d.value === best} onClick={() => select(d.verstr)} />
        ))}
      </div>
    </div>
  );
}

export default memo(MetricBarChart);
