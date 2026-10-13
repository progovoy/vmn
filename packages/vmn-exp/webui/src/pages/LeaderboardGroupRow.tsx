/** A group header row of the grouped board (plan 22 G4), spanning the
 *  table's columns: the fold, the group's label (a link group's target run,
 *  with its status), its runs' bar and status count (plan 22 F13: they
 *  belong to the group's head, not to a column), and per metric the
 *  group's aggregate (with a link target's own value), plus the `+N more`
 *  row under it. */
import type { CSSProperties } from "react";
import { Link } from "react-router-dom";
import type { GroupAggregate, GroupTarget } from "../apiGroups";
import StatusPill from "../components/StatusPill";
import { Icon } from "../components/shell/icons";
import type { ExperimentRow, RunState } from "../types";
import { fmtVal, runHref } from "../util";
import type { BoardGroup, GroupHeaderItem, GroupMoreItem, MemberPlace } from "../util/groupItems";
import { MORE_TEXT, aggregateCell, barSegments, countParts, countsText, spokenCounts } from "./groupHeaderText";
import { isGapId } from "./leaderboardColumns";
import { HeaderCheckbox, type HeaderCheckProps } from "./LeaderboardHeadParts";
import { layoutIds, rowHeight, type RowLayout } from "./LeaderboardRow";
import "./leaderboardGroupRow.css";
import "./groupMembers.css";

/** What names the group: its target run, else its label. */
export const groupName = (label: string, t: GroupTarget | null) => (t ? t.name || t.verstr : label);

/** A group's counts as text: `5 of 16 runs · 1 failed`. */
export const groupCountsText = (g: BoardGroup) => countsText(g.counts, g.rows_unfiltered);

/** What a screen reader hears for a group's header. */
export const groupSpoken = (g: BoardGroup) =>
  `Group ${groupName(g.label, g.target)}: ${spokenCounts(g.counts, g.rows_unfiltered)}`;

/** `16 runs · 2 running · 1 failed`, each state in its colour (hidden from a
 *  screen reader, which gets them from groupSpoken). */
export function GroupCountParts({ group, title }: { group: BoardGroup; title?: string }) {
  return (
    <span className="group-counts" aria-hidden="true" title={title}>
      {countParts(group.counts, group.rows_unfiltered).map((p, i) => (
        <span key={p.tone}>{i > 0 && " · "}<span className={`tone-${p.tone}`}>{p.text}</span></span>
      ))}
    </span>
  );
}

/** The group's runs as one bar, like the run page's Fleet card: finished
 *  runs fill from the left, the waiting ones are the empty track (F13). */
export function GroupBar({ group }: { group: BoardGroup }) {
  const segments = barSegments(group.counts);
  if (!segments) return null;
  return (
    <span className="group-bar" aria-hidden="true">
      {segments.map((sg) => (
        <span key={sg.tone} className={`group-bar-seg tone-${sg.tone}`} data-tone={sg.tone} style={{ width: `${sg.pct}%` }} />
      ))}
    </span>
  );
}

function Label({ item, layout, first, onFold }: {
  item: GroupHeaderItem; layout: RowLayout; first?: ExperimentRow; onFold: (key: string) => void;
}) {
  const { group } = item;
  const t = group.target;
  const name = groupName(group.label, t);
  const code = !t && first;
  return (
    <div className="group-head">
      <div className="nest">
        <button
          className="fold-toggle" aria-expanded={item.open}
          aria-label={`${item.open ? "Collapse" : "Expand"} group ${name}`}
          onClick={() => onFold(group.key)}
        >
          <Icon name={item.open ? "chevron-down" : "chevron-right"} size={14} />
        </button>
        {t ? (
          <Link className={`group-label run-link${t.name ? " run-name" : " mono"}`} to={runHref(layout.runBase, t.verstr)} title={t.verstr}>
            {name}
          </Link>
        ) : (
          <span className={`group-label${code ? " mono" : ""}`} title={group.label}>{group.label}</span>
        )}
      </div>
      <div className="group-sub" title={groupCountsText(group)}>
        <GroupBar group={group} />
        <GroupCountParts group={group} />
        {code && <span className="group-code"> · {first.base_version} · {first.branch}</span>}
        <span className="sr-only">{groupSpoken(group)}</span>
      </div>
    </div>
  );
}

function AggregateCell({ id, item, agg, style }: {
  id: string; item: GroupHeaderItem; agg: GroupAggregate; style: CSSProperties;
}) {
  const name = id.slice(2);
  const { value, title } = aggregateCell(item.group.aggregates[name], agg);
  const own = item.group.target?.metrics[name];
  return (
    <td data-col-id={id} style={style} title={title} className="group-metric">
      {value !== null && <span className="metric group-agg">{fmtVal(value)}</span>}
      {typeof own === "number" && <span className="group-own">own {fmtVal(own)}</span>}
    </td>
  );
}

export function GroupHeaderRow({ item, index, isActive, layout, agg, first, onFold, check }: {
  item: GroupHeaderItem; index: number; isActive: boolean; layout: RowLayout;
  /** The aggregate the board shows. */
  agg: GroupAggregate;
  /** A code state's first row (its base version and branch). */
  first?: ExperimentRow;
  onFold: (key: string) => void;
  /** Its checkbox over the group's loaded rows. */
  check: Omit<HeaderCheckProps, "label">;
}) {
  const t = item.group.target;
  const status = (t?.tree_status ?? t?.status) as RunState | null | undefined;
  const cell = (id: string, style: CSSProperties) => {
    if (id.startsWith("m:")) return <AggregateCell key={id} id={id} item={item} agg={agg} style={style} />;
    const body = id === "check"
      ? item.rows.length > 0 && <HeaderCheckbox {...check} label={`Select group ${groupName(item.group.label, t)}`} />
      : id === "experiment" ? <Label item={item} layout={layout} first={first} onFold={onFold} />
      : id === "idx" && t?.idx != null ? `@${t.idx}`
      : id === "status" && status ? <StatusPill status={status} /> : null;
    const cls = id === "check" ? "check-cell" : id === "experiment" ? "exp-cell" : id === "idx" ? "idx-cell" : id === "status" ? "status-cell" : undefined;
    return <td key={id} data-col-id={id} style={style} className={cls} aria-hidden={isGapId(id) || undefined}>{body}</td>;
  };
  return (
    <tr
      className={`group-row${item.open ? "" : " shut"}`} style={{ height: rowHeight(layout) }}
      data-row-index={index} data-href={t ? runHref(layout.runBase, t.verstr) : undefined}
      tabIndex={isActive ? 0 : -1}
    >
      {layoutIds(layout).map((id, i) => cell(id, layout.styles[i]))}
    </tr>
  );
}

export function GroupMoreRow({ item, index, isActive, layout, onMore, member }: {
  item: GroupMoreItem; index: number; isActive: boolean; layout: RowLayout; onMore: (key: string) => void;
  member?: MemberPlace;
}) {
  const more = (
    <button
      type="button" className="group-more-btn" disabled={item.state === "loading"}
      role={item.state === "error" ? "alert" : undefined}
      onClick={() => onMore(item.key)}
    >
      {MORE_TEXT[item.state](item.remaining)}
    </button>
  );
  return (
    <tr className={`group-more ${item.state}${member ? " group-member group-last" : ""}`} style={{ height: rowHeight(layout) }} data-row-index={index} tabIndex={isActive ? 0 : -1}>
      {layoutIds(layout).map((id, i) => (
        <td key={id} data-col-id={id} style={layout.styles[i]}>
          {id === "experiment" && (member ? <div className="group-member-body">{more}</div> : more)}
        </td>
      ))}
    </tr>
  );
}
