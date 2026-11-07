/** The grouped Jobs view's header and `+N more` rows (plan 23 §3.4): a
 *  group of jobs spans the table, its fold (over 50 runs, its Filter to
 *  button), label, the jobs' status bar and their count, and in the value
 *  column the group's aggregate of its jobs' values (plan 31 §2). */
import MoreButton from "../../components/MoreButton";
import PolicyMixMark from "../../components/PolicyMixMark";
import { NO_GOAL, plural } from "../../util";
import type { BoardGroup, GroupHeaderItem, GroupMoreItem } from "../../util/groupItems";
import { jobGroupCell } from "../groupHeaderText";
import { GroupBar, GroupFold } from "../LeaderboardGroupRow";
import { HeaderCheckbox, type HeaderCheckProps } from "../LeaderboardHeadParts";
import { JOB_COLUMNS } from "./jobColumns";
import type { JobGroupActions } from "./JobsTable";

const SPAN = JOB_COLUMNS.length - 1;
const VALUE_AT = JOB_COLUMNS.findIndex((c) => c.id === "value");
/** The columns the label spans (after the checkbox) and the ones after the value. */
const BEFORE_VALUE = VALUE_AT - 1;
const AFTER_VALUE = JOB_COLUMNS.length - VALUE_AT - 1;

/** `median 0.65` of the group's jobs' values, titled by both aggregates;
 *  `— (no goal)`, `—`; nothing before the rows name their aggregate. */
export function JobGroupValue({ group, groups }: { group: BoardGroup; groups: JobGroupActions }) {
  if (!groups.rolled) return null;
  const c = jobGroupCell(group.job_aggregates?.[groups.rolled.metric ?? ""], groups.aggregate, groups.rolled);
  return (
    <span className="job-best" title={c.title}>
      {c.name && <span className="muted">{c.name} </span>}
      <span className={c.name ? "metric" : "muted"}>{c.value}</span>
      <PolicyMixMark text={c.mix} />
      {c.noGoal && <span className="goal">{NO_GOAL}</span>}
    </span>
  );
}

export function JobGroupRow({ item, index, isActive, height, groups, check }: {
  item: GroupHeaderItem; index: number; isActive: boolean; height: number;
  groups: JobGroupActions;
  check: Omit<HeaderCheckProps, "label">;
}) {
  const { group } = item;
  const size = plural(group.rows_total, groups.noun);
  return (
    <tr className={`group-row${item.open ? "" : " shut"}`} style={{ height }} data-row-index={index} tabIndex={isActive ? 0 : -1}>
      <td className="check-cell">
        {item.rows.length > 0 && <HeaderCheckbox {...check} label={`Select group ${group.label}`} />}
      </td>
      <td colSpan={BEFORE_VALUE} className="exp-cell">
        <div className="group-head">
          <div className="nest">
            {/* A group over 50 runs opens as its clause instead of unfolding. */}
            <GroupFold item={item} name={group.label} onFold={groups.onFold} asFilter={groups.asFilter} noun={groups.noun} />
            <span className="group-label" title={group.label}>{group.label}</span>
            <span className="group-sub">
              <GroupBar group={group} />
              <span className="group-counts">{size}</span>
            </span>
          </div>
        </div>
      </td>
      <td data-col-id="value" className="jobs-cell-value num"><JobGroupValue group={group} groups={groups} /></td>
      <td colSpan={AFTER_VALUE} />
    </tr>
  );
}

export function JobMoreRow({ item, index, isActive, height, onMore }: {
  item: GroupMoreItem; index: number; isActive: boolean; height: number; onMore: (key: string) => void;
}) {
  return (
    <tr className={`group-more ${item.state}`} style={{ height }} data-row-index={index} tabIndex={isActive ? 0 : -1}>
      <td />
      <td colSpan={SPAN}>
        <MoreButton item={item} onMore={onMore} />
      </td>
    </tr>
  );
}
