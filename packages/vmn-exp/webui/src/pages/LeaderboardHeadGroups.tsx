/** The row above the leaderboard's column headers that puts a grouped
 *  board's count columns under one "Runs in group" label (plan 22 F10). */
import type { CSSProperties } from "react";
import { STICKY_BG } from "./leaderboardColumns";
import { GROUP_COUNTS_HELP, GROUP_COUNTS_LABEL, type HeadGroup } from "./groupCountColumns";
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
 *  them would put the label over the wrong columns. */
export default function HeadGroups({ groups, styles, helpId }: {
  groups: readonly HeadGroup[];
  /** The column styles, one per column. */
  styles: readonly CSSProperties[];
  /** Id for the description the group cells and the count headers share. */
  helpId: string;
}) {
  const first = groups.find((g) => g.counts);
  const labelStyle: CSSProperties = { position: "sticky", left: pinnedEdge(styles) };
  return (
    <tr className="lb-group-row">
      {groups.map((g) => g.counts ? (
        <th
          key={g.start} scope="colgroup" colSpan={g.span} className="lb-group"
          style={groupStyle(styles[g.start] ?? {})} title={GROUP_COUNTS_HELP} aria-describedby={helpId}
        >
          <span className="lb-group-label" style={labelStyle}>{GROUP_COUNTS_LABEL}</span>
          {g === first && <span id={helpId} hidden>{GROUP_COUNTS_HELP}</span>}
        </th>
      ) : (
        <td key={g.start} className="lb-group-gap" style={groupStyle(styles[g.start] ?? {})} />
      ))}
    </tr>
  );
}
