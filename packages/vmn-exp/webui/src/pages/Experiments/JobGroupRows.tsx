/** The grouped Jobs view's header and `+N more` rows (plan 23 §3.4): a
 *  group of jobs spans the table, its fold (over 50 runs, its Filter to
 *  button), label, the jobs' status bar and
 *  their count. */
import { plural } from "../../util";
import type { GroupHeaderItem, GroupMoreItem } from "../../util/groupItems";
import { GroupBar, GroupFold } from "../LeaderboardGroupRow";
import type { GroupFilter } from "../LeaderboardTable";
import { HeaderCheckbox, type HeaderCheckProps } from "../LeaderboardHeadParts";
import { MORE_TEXT } from "../groupHeaderText";
import { JOB_COLUMNS } from "./jobColumns";

const SPAN = JOB_COLUMNS.length - 1;

export function JobGroupRow({ item, index, isActive, height, onFold, asFilter, noun, check }: {
  item: GroupHeaderItem; index: number; isActive: boolean; height: number;
  onFold: (key: string) => void;
  /** A group over 50 runs opens as its clause instead of unfolding. */
  asFilter?: GroupFilter;
  noun: string;
  check: Omit<HeaderCheckProps, "label">;
}) {
  const { group } = item;
  const size = plural(group.rows_total, noun);
  return (
    <tr className={`group-row${item.open ? "" : " shut"}`} style={{ height }} data-row-index={index} tabIndex={isActive ? 0 : -1}>
      <td className="check-cell">
        {item.rows.length > 0 && <HeaderCheckbox {...check} label={`Select group ${group.label}`} />}
      </td>
      <td colSpan={SPAN} className="exp-cell">
        <div className="group-head">
          <div className="nest">
            <GroupFold item={item} name={group.label} onFold={onFold} asFilter={asFilter} noun={noun} />
            <span className="group-label" title={group.label}>{group.label}</span>
            <span className="group-sub">
              <GroupBar group={group} />
              <span className="group-counts">{size}</span>
            </span>
          </div>
        </div>
      </td>
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
        <button
          type="button" className="group-more-btn" disabled={item.state === "loading"}
          role={item.state === "error" ? "alert" : undefined} onClick={() => onMore(item.key)}
        >
          {MORE_TEXT[item.state](item.remaining)}
        </button>
      </td>
    </tr>
  );
}
