import { fmtVal } from "../util";
import { Y_AXIS_SIZE, type CurveSeries } from "../util/curveOptions";
import type { TooltipRow } from "../util/seriesArrays";
import type { CursorInfo } from "./UPlotChart";

export default function CurveTooltip({ rows, series, cursor, width, formatX }: {
  rows: TooltipRow[];
  series: CurveSeries[];
  cursor: CursorInfo;
  width: number;
  formatX: (x: number) => string;
}) {
  const byKey = new Map(series.map((s) => [s.key, s]));
  const left = cursor.left + Y_AXIS_SIZE;
  // Past the middle the box opens to the left of the cursor, never off-card.
  const flip = width > 0 && left > width / 2;
  return (
    <div
      data-testid="curve-tooltip"
      style={{
        position: "absolute",
        top: Math.max(0, cursor.top - 10),
        left: flip ? left - 12 : left + 12,
        transform: flip ? "translateX(-100%)" : undefined,
        pointerEvents: "none",
        background: "var(--panel-2)",
        border: "1px solid var(--line)",
        borderRadius: 8,
        color: "var(--text)",
        fontSize: 11.5,
        padding: "6px 8px",
        zIndex: 5,
        whiteSpace: "nowrap",
      }}
    >
      <div className="mono" style={{ color: "var(--text-3)", marginBottom: 4 }}>{formatX(rows[0].x)}</div>
      {rows.map((r) => {
        const s = byKey.get(r.key);
        return (
          <div key={r.key} data-key={r.key} style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{ width: 10, height: 3, borderRadius: 2, background: s?.color }} />
            <span style={{ color: "var(--text-2)", flex: 1 }}>{s?.label ?? r.key}</span>
            <span className="mono">{fmtVal(r.value)}</span>
          </div>
        );
      })}
    </div>
  );
}
