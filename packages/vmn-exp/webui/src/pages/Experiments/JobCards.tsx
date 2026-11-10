/** The Jobs view below 640px (plan 23 W1): a card per top-level run (name,
 *  status, a job's progress, its best value) in the board's card style;
 *  grouped, a section label per group of jobs. An outer run's expander
 *  opens its tree under the card, as the grid's row does (plan 28 N6). */
import { memo } from "react";
import { Link } from "react-router-dom";
import RowCheckbox from "../../components/RowCheckbox";
import StatusPill from "../../components/StatusPill";
import TreeToggle from "../../components/TreeToggle";
import { useRowNavigate } from "../../hooks/useRowNavigate";
import type { ExperimentRow } from "../../types";
import { plural, runHref } from "../../util";
import { jobWhen, jobWhenText } from "../../util/jobWhen";
import { isGroupItem, type BoardItem, type GroupHeaderItem } from "../../util/groupItems";
import { HeaderCheckbox } from "../LeaderboardHeadParts";
import { CardGroupMore } from "../LeaderboardCardGroup";
import { headStatus } from "../LeaderboardRow";
import JobTree from "../Job/JobTree";
import { AttentionChips, BaselineCell, JobSubLine, ValueCell, type JobContext } from "./JobCells";
import { JobGroupCounts, JobGroupValue } from "./JobGroupRows";
import { foldable, type JobsTableProps } from "./JobsTable";
import { isTreeSlot, useTreeSlots } from "./JobsTreeSlot";
import "../leaderboardCards.css";

const NO_ITEMS: BoardItem[] = [];

const JobCard = memo(function JobCard({ r, ctx, selected, onToggle, expanded, onExpand }: {
  r: ExperimentRow; ctx: JobContext; selected: boolean;
  onToggle: (verstr: string, range: boolean) => void;
  /** Whether its tree is open under it, and what opens or folds it. */
  expanded: boolean; onExpand?: (verstr: string) => void;
}) {
  const href = runHref(ctx.runBase, r.verstr);
  const status = headStatus(r);
  const onClick = useRowNavigate(href);
  return (
    <li className={`lb-mcard job-mcard${selected ? " checked" : ""}${r.archived ? " archived" : ""}`} onClick={onClick}>
      <RowCheckbox verstr={r.verstr} checked={selected} onToggle={onToggle} />
      <div className="lb-mcard-body">
        <div className="lb-mcard-head">
          {r.job && onExpand && <TreeToggle label={r.name || r.verstr} expanded={expanded} onToggle={() => onExpand(r.verstr)} />}
          <Link className={`lb-mcard-name run-link${r.name ? " run-name" : " mono"}`} to={href} title={r.verstr}>
            {r.name || r.verstr}
          </Link>
          {status && <StatusPill status={status} exitCode={r.exit_code} durationSec={r.duration_sec} staleSec={r.stale_sec} errorSummary={r.error_summary} lost={r.job?.lost} />}
        </div>
        <div className="lb-mcard-sub"><JobSubLine r={r} /><AttentionChips r={r} ctx={ctx} /><BaselineCell r={r} ctx={ctx} /></div>
        <div className="lb-mcard-metric job-mcard-best"><ValueCell r={r} ctx={ctx} /></div>
        <div className="lb-mcard-foot mono">@{r.idx}{r.branch ? ` · ${r.branch}` : ""} · {jobWhenText(jobWhen(r))}</div>
      </div>
    </li>
  );
});

/** A group's section label: its fold, or over 50 runs its Filter to button. */
function CardGroupLabel({ item, groups }: { item: GroupHeaderItem; groups: JobsTableProps["groups"] }) {
  const { group } = item;
  const clause = item.asFilter ? groups.asFilter?.clauseOf(group) : null;
  if (clause) {
    return (
      <button type="button" className="fold-toggle" onClick={() => groups.asFilter!.onFilter(clause)}>
        Filter to {clause} ({plural(group.rows_total, groups.noun)})
      </button>
    );
  }
  return (
    <button type="button" className="fold-toggle" aria-expanded={item.open} onClick={() => groups.onFold(group.key)}>
      {group.label}
    </button>
  );
}

export default function JobCards({ items, ctx, selected, headerCheck, groups, onToggle, emptyText, trees, heads }: JobsTableProps) {
  const metricLabel = heads?.value?.label ?? ctx.metric;
  const slots = useTreeSlots(items ?? NO_ITEMS);
  return (
    <div className="lb-mcards-wrap">
      <div className="lb-mcards-head">
        <HeaderCheckbox {...headerCheck} />
        {metricLabel && <span className="lb-mcards-metric">{metricLabel}</span>}
      </div>
      {items === undefined ? (
        <p className="lb-mcards-loading" role="status">loading outer runs…</p>
      ) : items.length === 0 ? (
        <p className="lb-mcards-loading">{emptyText}</p>
      ) : (
        <ul className="lb-mcards" role="list" aria-label="outer runs">
          {slots.list.map((it) => {
            if (isTreeSlot(it)) {
              return trees && (
                <li key={`tree:${it.row.verstr}`} className="lb-mcard-tree">
                  <JobTree ws={trees.ws} app={trees.app} verstr={it.row.verstr} name={it.row.name || undefined}
                    attention={ctx.attention} embedded />
                </li>
              );
            }
            if (!isGroupItem(it)) {
              return (
                <JobCard
                  key={it.verstr} r={it} ctx={ctx} selected={selected.has(it.verstr)} onToggle={onToggle}
                  expanded={slots.open.has(it.verstr)} onExpand={trees ? slots.toggle : undefined}
                />
              );
            }
            if (it.item === "more") return <CardGroupMore key={`more:${it.key}`} item={it} onMore={groups.onMore} />;
            return (
              <li key={`group:${it.group.key}`} className="lb-mcard-group">
                {foldable(groups, it)
                  ? <CardGroupLabel item={it} groups={groups} />
                  : <span className="group-label">{it.group.label}</span>}
                <JobGroupValue group={it.group} groups={groups} />
                {groups.oneRow && <JobGroupCounts group={it.group} />}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
