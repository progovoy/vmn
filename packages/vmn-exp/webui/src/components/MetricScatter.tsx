import { memo, useMemo, useState } from "react";
import type { ExperimentRow, MetricsSchema } from "../types";
import { fmtVal, metricGoal } from "../util";
import { chartTheme } from "../util/cssColor";
import { useThemeVersion } from "../hooks/useTheme";
import { Y_AXIS_SIZE } from "../util/curveOptions";
import { nearestPoint, scatterGroups } from "../util/scatterData";
import { DENSE_POINTS, scatterData, scatterOptions } from "../util/scatterOptions";
import { TOOLTIP_STYLE } from "./chartStyles";
import { useRunSelect } from "./chartHooks";
import UPlotChart, { type CursorInfo } from "./UPlotChart";

interface Props {
  rows: ExperimentRow[];
  metricCols: string[];
  paramCols: string[];
  schema: MetricsSchema | null;
  /** Called with a clicked point's run; defaults to opening the run page. */
  onSelect?: (verstr: string) => void;
}

const HEIGHT = 320;
/** How near (as a fraction of each axis span) the cursor must be to a point. */
const HIT_RADIUS = 0.03;
const COLORS = ["var(--accent)", "var(--good)"];

function AxisSelect({ label, value, cols, onChange }: {
  label: string; value: string; cols: string[]; onChange: (v: string) => void;
}) {
  return (
    <label style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 12 }}>
      {label}
      <select role="combobox" value={value} onChange={(e) => onChange(e.target.value)} style={{ minWidth: 80 }}>
        {cols.map((c) => <option key={c} value={c}>{c}</option>)}
      </select>
    </label>
  );
}

/** Canvas scatter (uPlot) of any metric or numeric param against another;
 *  the best point by the y metric's goal is highlighted. Hover shows the
 *  nearest run, click opens it. */
function MetricScatter({ rows, metricCols, paramCols, schema, onSelect }: Props) {
  const allCols = useMemo(() => [...metricCols, ...paramCols], [metricCols, paramCols]);
  const [xCol, setXCol] = useState(metricCols[0] ?? paramCols[0] ?? "");
  const [yCol, setYCol] = useState(metricCols[1] ?? paramCols[0] ?? metricCols[0] ?? "");
  const yGoal = metricGoal(schema, yCol);
  const select = useRunSelect(onSelect);

  const groups = useMemo(() => {
    const { rest, best } = scatterGroups(rows, xCol, yCol, paramCols, yGoal);
    return [rest, best]; // in COLORS order
  }, [rows, xCol, yCol, paramCols, yGoal]);
  const dense = groups.reduce((n, g) => n + g.xs.length, 0) > DENSE_POINTS;
  // Fresh rows (a poll) swap data in place; only the point-size tier rebuilds.
  const themeVersion = useThemeVersion();
  const options = useMemo(
    () => scatterOptions(COLORS, { height: HEIGHT, theme: chartTheme(), dense }), [dense, themeVersion],
  );
  const data = useMemo(() => scatterData(groups), [groups]);

  const [cursor, setCursor] = useState<CursorInfo | null>(null);
  const hovered = useMemo(
    () => (cursor ? nearestPoint(groups, cursor.x, cursor.y, HIT_RADIUS) : null),
    [cursor, groups],
  );

  return (
    <div className="card">
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12 }}>
        <div className="eyebrow" style={{ marginBottom: 0 }}>scatter plot</div>
        <AxisSelect label="X" value={xCol} cols={allCols} onChange={setXCol} />
        <AxisSelect label="Y" value={yCol} cols={allCols} onChange={setYCol} />
      </div>
      <div
        data-testid="scatter-chart"
        style={{ position: "relative", width: "100%", cursor: hovered ? "pointer" : undefined }}
        onClick={() => hovered && select(hovered.verstr)}
      >
        <UPlotChart options={options} data={data} onCursor={setCursor} />
        {cursor && hovered && (
          <div
            data-testid="scatter-tooltip"
            style={{ ...TOOLTIP_STYLE, top: cursor.top + 12, left: cursor.left + Y_AXIS_SIZE + 12 }}
          >
            <div className="mono">@{hovered.idx} <span style={{ color: "var(--text-3)" }}>{hovered.verstr}</span></div>
            <div>{xCol}: <span className="mono">{fmtVal(hovered.x)}</span></div>
            <div>{yCol}: <span className="mono">{fmtVal(hovered.y)}</span></div>
          </div>
        )}
      </div>
    </div>
  );
}

/** Memoized: the leaderboard re-polls, and identical rows must not redraw
 *  thousands of points. */
export default memo(MetricScatter);
