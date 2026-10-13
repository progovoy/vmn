/** A group header row of the grouped board (plan 22 G4), spanning the
 *  table's columns: the fold, the group's label (a link group's target run,
 *  with its status), the status count (its size alone while the count
 *  columns show the states, F10), the count columns, and per metric the
 *  group's aggregate (with a link target's own value), plus the `+N more`
 *  row under it. */
import type { CSSProperties } from "react";
import { Link } from "react-router-dom";
import type { GroupAggregate, GroupTarget } from "../apiGroups";
import StatusPill from "../components/StatusPill";
import { Icon } from "../components/shell/icons";
import type { ExperimentRow, RunState } from "../types";
import { fmtVal, runHref } from "../util";
import type { BoardGroup, GroupHeaderItem, GroupMoreItem } from "../util/groupItems";
import { MORE_TEXT, aggregateCell, countParts, countsText, sizeText, spokenCounts } from "./groupHeaderText";
import { GROUP_COUNT_COLS, groupCount, groupCountTone, isGroupCountId, type GroupCountCol } from "./groupCountColumns";
import { isGapId } from "./leaderboardColumns";
import { HeaderCheckbox, type HeaderCheckProps } from "./LeaderboardHeadParts";
import { ROW_HEIGHT, layoutIds, type RowLayout } from "./LeaderboardRow";
import "./leaderboardGroupRow.css";

/** What names the group: its target run, else its label. */
export const groupName = (label: string, t: GroupTarget | null) => (t ? t.name || t.verstr : label);

/** A group's counts as text: `5 of 16 runs · 1 failed`. */
export const groupCountsText = (g: BoardGroup) => countsText(g.counts, g.rows_unfiltered);

/** What a screen reader hears for a group's header. */
export const groupSpoken = (g: BoardGroup) =>
  `Group ${groupName(g.label, g.target)}: ${spokenCounts(g.counts, g.rows_unfiltered)}`;

/** `16 runs · 2 running · 1 failed`, each state in its colour (hidden from a
 *  screen reader, which gets them from groupSpoken); only `16 runs` when
 *  *sizeOnly* (the count columns show the states). */
export function GroupCountParts({ group, className = "", title, sizeOnly = false }: {
  group: BoardGroup; className?: string; title?: string; sizeOnly?: boolean;
}) {
  const parts = sizeOnly
    ? [{ text: sizeText(group.counts, group.rows_unfiltered), tone: "total" }]
    : countParts(group.counts, group.rows_unfiltered);
  return (
    <span className={`group-counts ${className}`.trim()} aria-hidden="true" title={title}>
      {parts.map((p, i) => (
        <span key={p.tone}>{i > 0 && " · "}<span className={`tone-${p.tone}`}>{p.text}</span></span>
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
  // From the fleet columns, not the ids: a windowed row leaves out the ones scrolled away.
  const sizeOnly = Boolean(layout.fleetCols?.some((c) => (GROUP_COUNT_COLS as readonly string[]).includes(c)));
  return (
    <div className="group-head">
      <div className="nest">
        {item.foldable && (
          <button
            className="fold-toggle" aria-expanded={item.open}
            aria-label={`${item.open ? "Collapse" : "Expand"} group ${name}`}
            onClick={() => onFold(group.key)}
          >
            <Icon name={item.open ? "chevron-down" : "chevron-right"} size={14} />
          </button>
        )}
        {t ? (
          <Link className={`group-label run-link${t.name ? " run-name" : " mono"}`} to={runHref(layout.runBase, t.verstr)} title={t.verstr}>
            {name}
          </Link>
        ) : (
          <span className={`group-label${code ? " mono" : ""}`} title={group.label}>{group.label}</span>
        )}
      </div>
      <div className={`group-sub${item.foldable ? " under-fold" : ""}`} title={groupCountsText(group)}>
        <GroupCountParts group={group} sizeOnly={sizeOnly} />
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

/** A count column's cell: the group's count, coloured by its state (muted at zero). */
function CountCell({ id, item, style }: { id: string; item: GroupHeaderItem; style: CSSProperties }) {
  const col = id.slice(2) as GroupCountCol;
  const n = groupCount(item.group.counts, col);
  return (
    <td data-col-id={id} style={style} className={`num fleet-cell group-count ${groupCountTone(col, n)}`}>{n}</td>
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
    if (isGroupCountId(id)) return <CountCell key={id} id={id} item={item} style={style} />;
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
      className={`group-row${item.open ? "" : " shut"}`} style={{ height: ROW_HEIGHT }}
      data-row-index={index} data-href={t ? runHref(layout.runBase, t.verstr) : undefined}
      tabIndex={isActive ? 0 : -1}
    >
      {layoutIds(layout).map((id, i) => cell(id, layout.styles[i]))}
    </tr>
  );
}

export function GroupMoreRow({ item, index, layout, onMore }: {
  item: GroupMoreItem; index: number; layout: RowLayout; onMore: (key: string) => void;
}) {
  return (
    <tr className={`group-more ${item.state}`} style={{ height: ROW_HEIGHT }} data-row-index={index} tabIndex={-1}>
      {layoutIds(layout).map((id, i) => (
        <td key={id} data-col-id={id} style={layout.styles[i]}>
          {id === "experiment" && (
            <button
              type="button" className="group-more-btn" disabled={item.state === "loading"}
              role={item.state === "error" ? "alert" : undefined}
              onClick={() => onMore(item.key)}
            >
              {MORE_TEXT[item.state](item.remaining)}
            </button>
          )}
        </td>
      ))}
    </tr>
  );
}
