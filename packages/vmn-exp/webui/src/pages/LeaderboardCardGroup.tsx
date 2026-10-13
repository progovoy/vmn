/** A grouped board's group below 640px (plan 22 G9): a sticky section label
 *  — its checkbox, the fold, the group's name (a link group's target run),
 *  its status count and its aggregate on the card metric — above the cards,
 *  and a `+N more` button under them. */
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import type { GroupAggregate } from "../apiGroups";
import { Icon } from "../components/shell/icons";
import { fmtVal, runHref } from "../util";
import type { GroupHeaderItem, GroupMoreItem } from "../util/groupItems";
import { MORE_TEXT, aggregateCell, shownAggregate } from "./groupHeaderText";
import { GroupBar, GroupCountParts, groupCountsText, groupName, groupSpoken } from "./LeaderboardGroupRow";
import { HeaderCheckbox, type HeaderCheckProps } from "./LeaderboardHeadParts";
import type { RowLayout } from "./LeaderboardRow";
import type { GroupActions } from "./LeaderboardTable";
import "./leaderboardGroupRow.css";
import "./leaderboardCardGroup.css";

function Aggregate({ item, metric, agg }: { item: GroupHeaderItem; metric: string; agg: GroupAggregate }) {
  const a = item.group.aggregates[metric];
  const { value, title } = aggregateCell(a, agg);
  if (value === null) return null;
  return (
    <span className="lb-mgroup-agg" title={title}>
      <span className="lb-mgroup-value metric">{fmtVal(value)}</span>
      <span className="lb-mgroup-metric">{metric} {shownAggregate(a, agg)}</span>
    </span>
  );
}

function CardGroupHead({ item, layout, metric, agg, mono, onFold, check }: {
  item: GroupHeaderItem; layout: RowLayout; metric: string | null; agg: GroupAggregate; mono: boolean;
  onFold: (key: string) => void;
  /** Its checkbox over the group's loaded cards (plan 22 F8). */
  check: Omit<HeaderCheckProps, "label">;
}) {
  const { group } = item;
  const t = group.target;
  const name = groupName(group.label, t);
  return (
    <div className={`lb-mgroup-head${item.open ? "" : " shut"}`}>
      {item.rows.length > 0 && <HeaderCheckbox {...check} label={`Select group ${name}`} />}
      <button
        className="fold-toggle" aria-expanded={item.open}
        aria-label={`${item.open ? "Collapse" : "Expand"} group ${name}`}
        onClick={() => onFold(group.key)}
      >
        <Icon name={item.open ? "chevron-down" : "chevron-right"} size={14} />
      </button>
      <div className="lb-mgroup-name">
        {t ? (
          <Link
            className={`lb-mgroup-label run-link${t.name ? " run-name" : " mono"}`}
            to={runHref(layout.runBase, t.verstr)} title={t.verstr}
          >
            {name}
          </Link>
        ) : (
          <span className={`lb-mgroup-label${mono ? " mono" : ""}`} title={group.label}>
            {group.label}
          </span>
        )}
        <span className="lb-mgroup-counts">
          <GroupBar group={group} />
          <GroupCountParts group={group} title={groupCountsText(group)} />
        </span>
        <span className="sr-only">{groupSpoken(group)}</span>
      </div>
      {metric && <Aggregate item={item} metric={metric} agg={agg} />}
    </div>
  );
}

export function CardGroupMore({ item, onMore }: { item: GroupMoreItem; onMore: (key: string) => void }) {
  return (
    <li className={`lb-mgroup-more ${item.state}`}>
      <button
        type="button" className="group-more-btn" disabled={item.state === "loading"}
        role={item.state === "error" ? "alert" : undefined}
        onClick={() => onMore(item.key)}
      >
        {MORE_TEXT[item.state](item.remaining)}
      </button>
    </li>
  );
}

/** One group's section: its label, then *cards* and its `+N more`. */
export default function CardGroup({ item, more, layout, metric, groups, children }: {
  item: GroupHeaderItem; more: GroupMoreItem | undefined; layout: RowLayout; metric: string | null;
  groups: GroupActions; children: ReactNode;
}) {
  const name = groupName(item.group.label, item.group.target);
  return (
    <li className="lb-mgroup">
      <CardGroupHead
        item={item} layout={layout} metric={metric} agg={groups.aggregate}
        mono={groups.field === "code_verstr"} onFold={groups.onFold}
        check={{ state: groups.checkOf(item.rows), onToggle: () => groups.onCheck(item.rows) }}
      />
      {item.open && (
        <ul className="lb-mcards" role="list" aria-label={`Runs of ${name}`}>
          {children}
          {more && <CardGroupMore item={more} onMore={groups.onMore} />}
        </ul>
      )}
    </li>
  );
}
