import { memo, useMemo, useState } from "react";
import type { ExperimentRow, MetricsSchema } from "../types";
import { fmtVal, metricGoal } from "../util";
import { chartTheme } from "../util/cssColor";
import { useThemeVersion } from "../hooks/useTheme";
import { Y_AXIS_SIZE } from "../util/curveOptions";
import { colorGroups, scatterGroups } from "../util/scatterData";
import { pointGrid } from "../util/pointGrid";
import { NO_GROUP_COLOR, type ChartGroups } from "../util/chartGroups";
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
  /** Axes to start from (the importance panel opens param vs metric). */
  initialX?: string;
  initialY?: string;
  /** Colours each point by its run's group (plan 22 G7). */
  groups?: ChartGroups;
  /** Controlled axes (plan 23 W4): *x* and *y* are plotted and a pick goes to *onAxes*. */
  x?: string;
  y?: string;
  onAxes?: (x: string, y: string) => void;
  /** The Y picker's choices, read as metrics even where a param shares a
   *  name (default: every column, a param's read from params). */
  yCols?: string[];
}

const HEIGHT = 320;
/** How near (as a fraction of each axis span) the cursor must be to a point. */
const HIT_RADIUS = 0.03;
const COLORS = ["var(--accent)", "var(--good)"];
const NO_PARAMS: string[] = [];

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
function MetricScatter({
  rows, metricCols, paramCols, schema, onSelect, initialX, initialY, groups: byGroup, x, y, onAxes, yCols,
}: Props) {
  // A numeric param folds into metrics too: one entry per name.
  const allCols = useMemo(() => [...new Set([...metricCols, ...paramCols])], [metricCols, paramCols]);
  const yParamCols = yCols ? NO_PARAMS : paramCols;
  const [ownX, setOwnX] = useState(initialX ?? metricCols[0] ?? paramCols[0] ?? "");
  const [ownY, setOwnY] = useState(initialY ?? metricCols[1] ?? paramCols[0] ?? metricCols[0] ?? "");
  const xCol = x ?? ownX, yCol = y ?? ownY;
  const setXCol = (v: string) => (onAxes ? onAxes(v, yCol) : setOwnX(v));
  const setYCol = (v: string) => (onAxes ? onAxes(xCol, v) : setOwnY(v));
  const yGoal = metricGoal(schema, yCol);
  const select = useRunSelect(onSelect);

  const colorOf = byGroup?.colorOf;
  const { colors, groups } = useMemo(() => {
    if (colorOf) return colorGroups(rows, xCol, yCol, paramCols, colorOf, NO_GROUP_COLOR, yParamCols);
    const { rest, best } = scatterGroups(rows, xCol, yCol, paramCols, yGoal, yParamCols);
    return { colors: COLORS, groups: [rest, best] };
  }, [rows, xCol, yCol, paramCols, yParamCols, yGoal, colorOf]);
  const colorsKey = colors.join("|");
  const shown = groups.reduce((n, g) => n + g.xs.length, 0);
  const dense = shown > DENSE_POINTS;
  // Fresh rows (a poll) swap data in place; only the point-size tier rebuilds.
  const themeVersion = useThemeVersion();
  const options = useMemo(
    // Rebuilt when the colours change, not each new array of them.
    () => scatterOptions(colors, { height: HEIGHT, theme: chartTheme(), dense }), [colorsKey, dense, themeVersion],
  );
  const data = useMemo(() => scatterData(groups), [groups]);

  const [cursor, setCursor] = useState<CursorInfo | null>(null);
  const grid = useMemo(() => pointGrid(groups, HIT_RADIUS), [groups]);
  const hovered = useMemo(() => (cursor ? grid.nearest(cursor.x, cursor.y) : null), [cursor, grid]);

  return (
    <div className="card">
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12 }}>
        <AxisSelect label="X" value={xCol} cols={allCols} onChange={setXCol} />
        <AxisSelect label="Y" value={yCol} cols={yCols ?? allCols} onChange={setYCol} />
      </div>
      <div
        data-testid="scatter-chart"
        style={{ position: "relative", width: "100%", cursor: hovered ? "pointer" : undefined }}
        onClick={() => hovered && select(hovered.verstr)}
      >
        {/* uPlot cannot build a scatter of no series: say so instead. */}
        {shown ? <UPlotChart options={options} data={data} onCursor={setCursor} />
          : <div className="empty">No run has both {xCol} and {yCol}.</div>}
        {cursor && hovered && (
          <div
            data-testid="scatter-tooltip"
            style={{ ...TOOLTIP_STYLE, top: cursor.top + 12, left: cursor.left + (cursor.plotLeft ?? Y_AXIS_SIZE) + 12 }}
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
