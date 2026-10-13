/** The Jobs view below 640px (plan 23 W1): a card per top-level run (name,
 *  status, a job's progress, its best value) in the board's card style;
 *  grouped, a section label per group of jobs. */
import { memo, type MouseEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import StatusPill from "../../components/StatusPill";
import type { ExperimentRow } from "../../types";
import { relTime, runHref } from "../../util";
import { isGroupItem } from "../../util/groupItems";
import { HeaderCheckbox } from "../LeaderboardHeadParts";
import { CardGroupMore } from "../LeaderboardCardGroup";
import { headStatus } from "../LeaderboardRow";
import { BestValue, JobSubLine, type JobContext } from "./JobCells";
import type { JobsTableProps } from "./JobsTable";
import "../leaderboardCards.css";

const JobCard = memo(function JobCard({ r, ctx, selected, onToggle, onPrefetch }: {
  r: ExperimentRow; ctx: JobContext; selected: boolean;
  onToggle: (verstr: string, range: boolean) => void;
  onPrefetch: (verstr: string) => void;
}) {
  const navigate = useNavigate();
  const href = runHref(ctx.runBase, r.verstr);
  const status = headStatus(r);
  const onClick = (e: MouseEvent) => {
    if ((e.target as HTMLElement).closest("a, input, button")) return;
    navigate(href);
  };
  return (
    <li className={`lb-mcard job-mcard${selected ? " checked" : ""}${r.archived ? " archived" : ""}`} onClick={onClick}>
      <input
        type="checkbox" checked={selected} aria-label={`Select ${r.verstr}`}
        onChange={() => {}} onClick={(e) => onToggle(r.verstr, e.shiftKey)}
      />
      <div className="lb-mcard-body">
        <div className="lb-mcard-head">
          <Link
            className={`lb-mcard-name run-link${r.name ? " run-name" : " mono"}`} to={href} title={r.verstr}
            onFocus={() => onPrefetch(r.verstr)}
          >
            {r.name || r.verstr}
          </Link>
          {status && <StatusPill status={status} exitCode={r.exit_code} durationSec={r.duration_sec} staleSec={r.stale_sec} errorSummary={r.error_summary} />}
        </div>
        <div className="lb-mcard-sub"><JobSubLine r={r} /></div>
        <div className="lb-mcard-metric job-mcard-best"><BestValue r={r} ctx={ctx} /></div>
        <div className="lb-mcard-foot mono">@{r.idx}{r.branch ? ` · ${r.branch}` : ""} · {relTime(r.started_at ?? r.timestamp)}</div>
      </div>
    </li>
  );
});

export default function JobCards({ items, ctx, selected, headerCheck, groups, onToggle, onPrefetch }: JobsTableProps) {
  return (
    <div className="lb-mcards-wrap">
      <div className="lb-mcards-head">
        <HeaderCheckbox {...headerCheck} />
        {ctx.metric && <span className="lb-mcards-metric">{ctx.metric}</span>}
      </div>
      {items === undefined ? (
        <p className="lb-mcards-loading" role="status">loading jobs…</p>
      ) : (
        <ul className="lb-mcards" role="list" aria-label="jobs">
          {items.map((it) => {
            if (!isGroupItem(it)) {
              return <JobCard key={it.verstr} r={it} ctx={ctx} selected={selected.has(it.verstr)} onToggle={onToggle} onPrefetch={onPrefetch} />;
            }
            if (it.item === "more") return <CardGroupMore key={`more:${it.key}`} item={it} onMore={groups.onMore} />;
            return (
              <li key={`group:${it.group.key}`} className="lb-mcard-group">
                <button type="button" className="fold-toggle" aria-expanded={it.open} onClick={() => groups.onFold(it.group.key)}>
                  {it.group.label}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
