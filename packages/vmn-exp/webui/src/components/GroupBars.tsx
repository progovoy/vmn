import { memo } from "react";
import { fmtVal } from "../util";

/** A group's mean ± std; both null when no run of the group has the metric. */
export interface GroupBar {
  group: string;
  count: number;
  mean: number | null;
  std: number | null;
}

const PLOT_H = 180;

/** Percent of *max*, rounded so float noise never leaks into the style. */
const pct = (v: number, max: number) => `${max > 0 ? Math.round((v / max) * 10000) / 100 : 0}%`;

function Bar({ b, mean, std, scale, color }: { b: GroupBar; mean: number; std: number; scale: number; color: string }) {
  return (
    <>
      <div
        data-testid="group-bar"
        data-group={b.group}
        title={`${b.group}: ${fmtVal(mean)} ± ${fmtVal(std)} (n=${b.count})`}
        style={{
          position: "absolute", bottom: 0, left: "15%", right: "15%",
          height: pct(Math.abs(mean), scale),
          background: color, opacity: 0.7, borderRadius: "4px 4px 0 0",
        }}
      />
      <div
        data-testid="group-whisker"
        style={{
          position: "absolute", left: "50%", width: 0,
          bottom: pct(Math.max(0, Math.abs(mean) - std), scale),
          height: pct(2 * std, scale),
          borderLeft: "1.5px solid var(--text-2)",
          pointerEvents: "none",
        }}
      />
    </>
  );
}

/** No value: no bar, a dash (plan 32 F12), never a bar at 0. */
const Missing = ({ b }: { b: GroupBar }) => (
  <div data-testid="group-missing" title={`${b.group}: no value (n=${b.count})`}
    style={{ position: "absolute", bottom: 4, width: "100%", color: "var(--text-3)" }}>—</div>
);

/** Vertical bars (group means) with ± std whiskers, in plain HTML. */
function GroupBars({ bars, color }: { bars: GroupBar[]; color: string }) {
  // Bars scale to the tallest mean; whiskers may reach above it.
  const scale = Math.max(0, ...bars.map((b) => Math.abs(b.mean ?? 0))) || 1;
  return (
    <div style={{ display: "flex", gap: 12, alignItems: "flex-end", overflowX: "auto", paddingTop: 12 }}>
      {bars.map((b) => (
        <div key={b.group} style={{ flex: "1 0 56px", maxWidth: 120, textAlign: "center" }}>
          <div style={{ position: "relative", height: PLOT_H, borderBottom: "1px solid var(--line)" }}>
            {b.mean === null
              ? <Missing b={b} />
              : <Bar b={b} mean={b.mean} std={b.std ?? 0} scale={scale} color={color} />}
          </div>
          <div className="mono" style={{ fontSize: 11, color: "var(--text-3)", marginTop: 4 }}>{b.group}</div>
        </div>
      ))}
    </div>
  );
}

export default memo(GroupBars);
