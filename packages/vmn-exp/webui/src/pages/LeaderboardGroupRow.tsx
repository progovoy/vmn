/** A group header row of the grouped board (plan 22 G4), spanning the
 *  table's columns: the fold, the group's label (a link group's target run,
 *  with its status), the status count, and per metric the group's aggregate
 *  (with a link target's own value), plus the `+N more` row under it. */
import type { CSSProperties } from "react";
import { Link } from "react-router-dom";
import type { GroupAggregate, GroupTarget } from "../apiGroups";
import StatusPill from "../components/StatusPill";
import { Icon } from "../components/shell/icons";
import type { ExperimentRow, RunState } from "../types";
import { fmtVal, runHref } from "../util";
import type { GroupHeaderItem, GroupMoreItem } from "../util/groupItems";
import { aggregateCell, countParts, countsText, spokenCounts } from "./groupHeaderText";
import { isGapId } from "./leaderboardColumns";
import { ROW_HEIGHT, layoutIds, type RowLayout } from "./LeaderboardRow";
import "./leaderboardGroupRow.css";

/** What names the group: its target run, else its label. */
const groupName = (label: string, t: GroupTarget | null) => (t ? t.name || t.verstr : label);

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
      <div className={`group-sub${item.foldable ? " under-fold" : ""}`} title={countsText(group.counts)}>
        <span className="group-counts" aria-hidden="true">
          {countParts(group.counts).map((p, i) => (
            <span key={p.tone}>{i > 0 && " · "}<span className={`tone-${p.tone}`}>{p.text}</span></span>
          ))}
        </span>
        {code && <span className="group-code"> · {first.base_version} · {first.branch}</span>}
        <span className="sr-only">{`Group ${name}: ${spokenCounts(group.counts)}`}</span>
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

export function GroupHeaderRow({ item, index, isActive, layout, agg, first, onFold }: {
  item: GroupHeaderItem; index: number; isActive: boolean; layout: RowLayout;
  /** The aggregate the board shows. */
  agg: GroupAggregate;
  /** A code state's first row (its base version and branch). */
  first?: ExperimentRow;
  onFold: (key: string) => void;
}) {
  const t = item.group.target;
  const status = (t?.tree_status ?? t?.status) as RunState | null | undefined;
  const cell = (id: string, style: CSSProperties) => {
    if (id.startsWith("m:")) return <AggregateCell key={id} id={id} item={item} agg={agg} style={style} />;
    const body = id === "experiment" ? <Label item={item} layout={layout} first={first} onFold={onFold} />
      : id === "idx" && t?.idx != null ? `@${t.idx}`
      : id === "status" && status ? <StatusPill status={status} /> : null;
    const cls = id === "experiment" ? "exp-cell" : id === "idx" ? "idx-cell" : id === "status" ? "status-cell" : undefined;
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

const MORE_TEXT = { idle: (n: number) => `+${n} more`, loading: () => "Loading…", error: () => "Could not load them, retry" };

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
