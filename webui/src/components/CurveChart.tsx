import { Fragment, memo, useMemo } from "react";
import {
  CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { smoothRows, type ChartRow, type XMode } from "../util/chartData";

export function fmtWallTick(ms: number): string {
  const d = new Date(ms);
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  const ss = String(d.getSeconds()).padStart(2, "0");
  return `${hh}:${mm}:${ss}`;
}

export function fmtRelTick(secs: number): string {
  if (secs < 60) return `${Math.round(secs)}s`;
  if (secs < 3600) return `${Math.round(secs / 60)}m`;
  return `${Math.round(secs / 3600)}h`;
}

const TOOLTIP_STYLE = {
  background: "var(--panel-2)",
  border: "1px solid var(--line)",
  borderRadius: 8,
  color: "var(--text)",
};

/** Line chart of `keys` over pre-built rows. Every Line uses `connectNulls`:
 *  rows are merged by x across series, so a sparse series has gaps between its
 *  own points that must not break the line. */
function CurveChart({ rows, keys, colorOf, alpha, xMode, height = 280 }: {
  rows: ChartRow[];
  keys: string[];
  colorOf: (key: string) => string;
  alpha: number;
  xMode: XMode;
  height?: number;
}) {
  const data = useMemo(() => smoothRows(rows, keys, alpha), [rows, keys, alpha]);
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data}>
        <CartesianGrid stroke="var(--line)" vertical={false} />
        <XAxis
          dataKey="x"
          type="number"
          domain={["dataMin", "dataMax"]}
          stroke="#85847a"
          tick={{ fontSize: 10.5, fontFamily: "var(--mono)" }}
          tickFormatter={
            xMode === "wall" ? fmtWallTick : xMode === "relative" ? fmtRelTick : undefined
          }
        />
        <YAxis stroke="#85847a" width={60} tick={{ fontSize: 10.5, fontFamily: "var(--mono)" }} />
        <Tooltip contentStyle={TOOLTIP_STYLE} />
        {keys.map((k) => (
          <Fragment key={k}>
            {alpha > 0 && (
              <Line
                type="monotone"
                dataKey={k}
                stroke={colorOf(k)}
                strokeWidth={1}
                strokeOpacity={0.3}
                strokeDasharray="4 2"
                dot={false}
                connectNulls
                isAnimationActive={false}
                name={`${k} (raw)`}
              />
            )}
            <Line
              type="monotone"
              dataKey={alpha > 0 ? `${k}__smooth` : k}
              stroke={colorOf(k)}
              strokeWidth={2}
              dot={false}
              connectNulls
              isAnimationActive={false}
              name={alpha > 0 ? `${k} (smooth)` : k}
            />
          </Fragment>
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}

export default memo(CurveChart);
