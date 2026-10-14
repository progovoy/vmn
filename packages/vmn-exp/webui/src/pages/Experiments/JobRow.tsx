/** One Jobs-view row (plan 23 W1, §3.1): a job, or a single run, across the
 *  JOB_COLUMNS. A click outside its links and checkbox opens the run. */
import { memo, useRef, type MouseEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import MatchingRunsChip from "../../components/MatchingRunsChip";
import StatusPill from "../../components/StatusPill";
import type { ExperimentRow } from "../../types";
import type { Density } from "../../util/density";
import { relTime, runHref } from "../../util";
import { HOVER_INTENT_MS, densityRowHeight, headStatus } from "../LeaderboardRow";
import type { JobCell } from "../../util/jobProgress";
import { BestValue, JobSubLine, SpreadCell, jobNumbers, type JobContext, type JobNumber } from "./JobCells";
import { CELL_CLASSES, COLUMN_STYLES, JOB_COLUMNS } from "./jobColumns";

/** When a top-level run started: its subtree's first start, else its own. */
const startedAt = (r: ExperimentRow) => r.job?.started_at ?? r.started_at ?? r.timestamp;

function titleOf(id: string, r: ExperimentRow, numbers: Record<JobNumber, JobCell>): string | undefined {
  if (id === "when") return startedAt(r) ?? undefined;
  return numbers[id as JobNumber]?.title;
}

function NameCell({ r, href, compact, ctx, onPrefetch }: {
  r: ExperimentRow; href: string; compact: boolean; ctx: JobContext; onPrefetch: (verstr: string) => void;
}) {
  return (
    <>
      <div className="nest">
        <Link
          className={`run-link${r.name ? " run-name" : " mono"}`} to={href} title={r.verstr}
          onFocus={() => onPrefetch(r.verstr)}
        >
          {r.name || r.verstr}
        </Link>
        <MatchingRunsChip r={r} runBase={ctx.runBase} search={ctx.search} />
        {compact && <span className="job-inline"><JobSubLine r={r} /></span>}
      </div>
      {!compact && <div className="exp-branch job-line"><JobSubLine r={r} /></div>}
    </>
  );
}

function JobRow({ r, index, isActive, isSelected, density, ctx, onToggle, onPrefetch }: {
  r: ExperimentRow; index: number;
  /** The table's one tab stop (roving tabindex). */
  isActive: boolean; isSelected: boolean;
  density?: Density; ctx: JobContext;
  onToggle: (verstr: string, range: boolean) => void;
  onPrefetch: (verstr: string) => void;
}) {
  const navigate = useNavigate();
  const hover = useRef<ReturnType<typeof setTimeout>>();
  const href = runHref(ctx.runBase, r.verstr);
  const numbers = jobNumbers(r);
  const status = headStatus(r);
  const onClick = (e: MouseEvent) => {
    if ((e.target as HTMLElement).closest("a, input, button")) return;
    navigate(href);
  };

  const body = (id: string) => {
    switch (id) {
      case "check":
        return (
          <input
            type="checkbox" checked={isSelected} aria-label={`Select ${r.verstr}`}
            onChange={() => {}} onClick={(e) => onToggle(r.verstr, e.shiftKey)}
          />
        );
      case "idx": return `@${r.idx}`;
      case "status":
        return status && (
          <StatusPill
            status={status} exitCode={r.exit_code} durationSec={r.duration_sec}
            staleSec={r.stale_sec} errorSummary={r.error_summary}
          />
        );
      case "name": return <NameCell r={r} href={href} compact={density === "compact"} ctx={ctx} onPrefetch={onPrefetch} />;
      case "best": return <BestValue r={r} ctx={ctx} />;
      case "spread": return <SpreadCell r={r} />;
      case "runs": case "failed": case "throughput": case "eta": return numbers[id].text;
      case "branch": return r.branch;
      case "when": return relTime(startedAt(r));
    }
    return null;
  };

  return (
    <tr
      style={{ height: densityRowHeight(density) }}
      className={`row job-row${isSelected ? " checked" : ""}${r.archived ? " archived" : ""}`}
      data-row-index={index} data-href={href} tabIndex={isActive ? 0 : -1}
      onClick={onClick}
      onMouseEnter={() => { hover.current = setTimeout(() => onPrefetch(r.verstr), HOVER_INTENT_MS); }}
      onMouseLeave={() => clearTimeout(hover.current)}
    >
      {JOB_COLUMNS.map((c, i) => (
        <td
          key={c.id} data-col-id={c.id} style={COLUMN_STYLES[i]} className={CELL_CLASSES[i]}
          title={titleOf(c.id, r, numbers)}
        >
          {body(c.id)}
        </td>
      ))}
    </tr>
  );
}

export default memo(JobRow);
