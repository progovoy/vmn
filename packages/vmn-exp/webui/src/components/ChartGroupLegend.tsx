/** The groups a grouped board's chart colours its runs by (plan 22 G7):
 *  a swatch, the group's name and its charted runs, the first few named. */
import { plural } from "../util";
import type { ChartGroup } from "../util/chartGroups";
import "./chartGroupLegend.css";

/** Groups named before the rest fold into `+N more`. */
export const LEGEND_SHOWN = 12;

export default function ChartGroupLegend({ legend }: { legend: readonly ChartGroup[] }) {
  if (!legend.length) return null;
  const rest = legend.length - LEGEND_SHOWN;
  return (
    <ul className="chart-group-legend" aria-label="Colour by group">
      {legend.slice(0, LEGEND_SHOWN).map((g) => (
        <li key={g.key} title={`${g.label}: ${plural(g.count, "run")}`}>
          <span className="swatch" style={{ background: g.color }} aria-hidden="true" />
          <span className="name">{g.label}</span>
          <span className="count">{g.count}</span>
        </li>
      ))}
      {rest > 0 && <li className="more">+{rest} more</li>}
    </ul>
  );
}
