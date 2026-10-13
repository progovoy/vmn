/** The row above the leaderboard's column headers that groups the inner-run
 *  count columns under one "Inner runs" label. */
import type { CSSProperties } from "react";
import { STICKY_BG } from "./leaderboardColumns";
import { INNER_RUNS_HELP, INNER_RUNS_LABEL, type HeadGroup } from "./innerRunColumns";
import "./leaderboardHead.css";

/** Height (px) of the group row; the column row sticks this far down. */
export const GROUP_ROW_HEIGHT = 26;

/** A group cell sticks to the top; over a pinned column it pins left too. */
function groupStyle(column: CSSProperties): CSSProperties {
  const style: CSSProperties = {
    position: "sticky", top: 0, zIndex: 2, background: STICKY_BG, height: GROUP_ROW_HEIGHT,
  };
  if (column.position === "sticky") return { ...style, left: column.left, zIndex: 4 };
  return style;
}

/** Right edge (px) of the pinned columns: the group label sticks there, so
 *  it stays readable while its block is partly scrolled under them. */
function pinnedEdge(styles: readonly CSSProperties[]): number {
  return styles.reduce((edge, st) => st.position === "sticky"
    ? Math.max(edge, Number(st.left ?? 0) + Number.parseFloat(String(st.width ?? 0)))
    : edge, 0);
}

/** Gap cells stay in the accessibility tree (empty, not aria-hidden):
 *  screen readers place a header by counting the row's cells, so hiding
 *  them would put "Inner runs" over the wrong columns. */
export default function HeadGroups({ groups, styles, helpId }: {
  groups: readonly HeadGroup[];
  /** The column styles, one per column. */
  styles: readonly CSSProperties[];
  /** Id for the description the group cells and the count headers share. */
  helpId: string;
}) {
  const first = groups.find((g) => g.inner);
  const labelStyle: CSSProperties = { position: "sticky", left: pinnedEdge(styles) };
  return (
    <tr className="lb-group-row">
      {groups.map((g) => g.inner ? (
        <th
          key={g.start} scope="colgroup" colSpan={g.span} className="lb-group"
          style={groupStyle(styles[g.start] ?? {})} title={INNER_RUNS_HELP} aria-describedby={helpId}
        >
          <span className="lb-group-label" style={labelStyle}>{INNER_RUNS_LABEL}</span>
          {g === first && <span id={helpId} hidden>{INNER_RUNS_HELP}</span>}
        </th>
      ) : (
        <td key={g.start} className="lb-group-gap" style={groupStyle(styles[g.start] ?? {})} />
      ))}
    </tr>
  );
}
