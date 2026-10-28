/** The Jobs view below 640px (plan 23 W1): a card per top-level run (name,
 *  status, a job's progress, its best value) in the board's card style;
 *  grouped, a section label per group of jobs. */
import { memo } from "react";
import { Link } from "react-router-dom";
import RowCheckbox from "../../components/RowCheckbox";
import StatusPill from "../../components/StatusPill";
import { useRowNavigate } from "../../hooks/useRowNavigate";
import type { ExperimentRow } from "../../types";
import { plural, relTime, runHref } from "../../util";
import { isGroupItem, type GroupHeaderItem } from "../../util/groupItems";
import { HeaderCheckbox } from "../LeaderboardHeadParts";
import { CardGroupMore } from "../LeaderboardCardGroup";
import { headStatus } from "../LeaderboardRow";
import { AttentionChips, BaselineCell, BestValue, JobSubLine, type JobContext } from "./JobCells";
import type { JobsTableProps } from "./JobsTable";
import "../leaderboardCards.css";

const JobCard = memo(function JobCard({ r, ctx, selected, onToggle }: {
  r: ExperimentRow; ctx: JobContext; selected: boolean;
  onToggle: (verstr: string, range: boolean) => void;
}) {
  const href = runHref(ctx.runBase, r.verstr);
  const status = headStatus(r);
  const onClick = useRowNavigate(href);
  return (
    <li className={`lb-mcard job-mcard${selected ? " checked" : ""}${r.archived ? " archived" : ""}`} onClick={onClick}>
      <RowCheckbox verstr={r.verstr} checked={selected} onToggle={onToggle} />
      <div className="lb-mcard-body">
        <div className="lb-mcard-head">
          <Link className={`lb-mcard-name run-link${r.name ? " run-name" : " mono"}`} to={href} title={r.verstr}>
            {r.name || r.verstr}
          </Link>
          {status && <StatusPill status={status} exitCode={r.exit_code} durationSec={r.duration_sec} staleSec={r.stale_sec} errorSummary={r.error_summary} />}
        </div>
        <div className="lb-mcard-sub"><JobSubLine r={r} /><AttentionChips r={r} ctx={ctx} /><BaselineCell r={r} ctx={ctx} /></div>
        <div className="lb-mcard-metric job-mcard-best"><BestValue r={r} ctx={ctx} /></div>
        <div className="lb-mcard-foot mono">@{r.idx}{r.branch ? ` · ${r.branch}` : ""} · {relTime(r.started_at ?? r.timestamp)}</div>
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

export default function JobCards({ items, ctx, selected, headerCheck, groups, onToggle, emptyText }: JobsTableProps) {
  return (
    <div className="lb-mcards-wrap">
      <div className="lb-mcards-head">
        <HeaderCheckbox {...headerCheck} />
        {ctx.metric && <span className="lb-mcards-metric">{ctx.metric}</span>}
      </div>
      {items === undefined ? (
        <p className="lb-mcards-loading" role="status">loading outer runs…</p>
      ) : items.length === 0 ? (
        <p className="lb-mcards-loading">{emptyText}</p>
      ) : (
        <ul className="lb-mcards" role="list" aria-label="outer runs">
          {items.map((it) => {
            if (!isGroupItem(it)) {
              return <JobCard key={it.verstr} r={it} ctx={ctx} selected={selected.has(it.verstr)} onToggle={onToggle} />;
            }
            if (it.item === "more") return <CardGroupMore key={`more:${it.key}`} item={it} onMore={groups.onMore} />;
            return (
              <li key={`group:${it.group.key}`} className="lb-mcard-group">
                <CardGroupLabel item={it} groups={groups} />
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
