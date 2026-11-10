/** The grouped Jobs view's header and `+N more` rows (plan 23 §3.4): a
 *  group of jobs spans the table, its fold (over 50 runs, its Filter to
 *  button), label, the jobs' status bar and their count, and in the value
 *  column the rows' aggregate of its jobs' units pooled (plan 34 §1). One
 *  row per group: no fold, the value's coverage and the jobs' run counts. */
import MoreButton from "../../components/MoreButton";
import PolicyMixMark from "../../components/PolicyMixMark";
import { NO_GOAL, plural } from "../../util";
import type { RunGroup } from "../../apiGroups";
import type { BoardGroup, GroupHeaderItem, GroupMoreItem } from "../../util/groupItems";
import { attemptCountsText, jobGroupCell } from "../groupHeaderText";
import { GroupBar, GroupFold } from "../LeaderboardGroupRow";
import { HeaderCheckbox, type HeaderCheckProps } from "../LeaderboardHeadParts";
import { JOB_COLUMNS } from "./jobColumns";
import { foldable, type JobGroupActions } from "./JobsTable";

const SPAN = JOB_COLUMNS.length - 1;
const VALUE_AT = JOB_COLUMNS.findIndex((c) => c.id === "value");
/** The columns the label spans (after the checkbox) and the ones after the value. */
const BEFORE_VALUE = VALUE_AT - 1;
const AFTER_VALUE = JOB_COLUMNS.length - VALUE_AT - 1;

/** `median 0.65` of the group's jobs' units pooled, titled like a row's;
 *  `— (no goal)`, `—`; nothing before the board names its aggregate. One
 *  row per group adds the coverage, `median 0.65 14/16`. */
export function JobGroupValue({ group, groups }: { group: BoardGroup; groups: JobGroupActions }) {
  if (!groups.rolled) return null;
  const c = jobGroupCell(group.job_aggregates?.[groups.rolled.metric ?? ""], groups.rolled);
  return (
    <span className="job-best" title={c.title}>
      {c.name && <span className="muted">{c.name} </span>}
      <span className={c.name ? "metric" : "muted"}>{c.value}</span>
      <PolicyMixMark text={c.mix} />
      {c.noGoal && <span className="goal">{NO_GOAL}</span>}
      {groups.oneRow && c.coverage && <span className="muted"> {c.coverage}</span>}
    </span>
  );
}

/** One row per group: the run counts summed over its outer runs, and their lost runs. */
export function JobGroupCounts({ group }: { group: Pick<RunGroup, "run_counts" | "lost"> }) {
  if (!group.run_counts) return null;
  return <span className="group-counts">{attemptCountsText(group.run_counts, group.lost)}</span>;
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
            {foldable(groups, item) && (
              <GroupFold item={item} name={group.label} onFold={groups.onFold} asFilter={groups.asFilter} noun={groups.noun} />
            )}
            <span className="group-label" title={group.label}>{group.label}</span>
            <span className="group-sub">
              <GroupBar group={group} />
              <span className="group-counts">{size}</span>
              {groups.oneRow && <JobGroupCounts group={group} />}
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
