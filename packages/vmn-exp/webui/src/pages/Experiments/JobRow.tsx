/** One Jobs-view row (plan 23 W1, §3.1): a job, or a single run, across the
 *  JOB_COLUMNS. A click outside its links and checkbox opens the run; a
 *  job's expander opens its tree under the row (plan 28 N6). */
import { memo } from "react";
import { Link } from "react-router-dom";
import MatchingRunsChip from "../../components/MatchingRunsChip";
import RowCheckbox from "../../components/RowCheckbox";
import StatusPill from "../../components/StatusPill";
import TreeToggle from "../../components/TreeToggle";
import type { ExperimentRow } from "../../types";
import type { Density } from "../../util/density";
import { useRowNavigate } from "../../hooks/useRowNavigate";
import { runHref } from "../../util";
import { jobWhen, jobWhenText, jobWhenTitle, type JobWhen } from "../../util/jobWhen";
import { densityRowHeight, headStatus } from "../LeaderboardRow";
import type { JobCell } from "../../util/jobProgress";
import { AttentionChips, BaselineCell, JobSubLine, SpreadCell, ValueCell, jobNumbers, type JobContext, type JobNumber } from "./JobCells";
import { CELL_CLASSES, COLUMN_STYLES, JOB_COLUMNS } from "./jobColumns";

function titleOf(id: string, when: JobWhen, numbers: Record<JobNumber, JobCell>): string | undefined {
  if (id === "when") return jobWhenTitle(when);
  return numbers[id as JobNumber]?.title;
}

function NameCell({ r, href, compact, ctx, expanded, onExpand }: {
  r: ExperimentRow; href: string; compact: boolean; ctx: JobContext;
  expanded: boolean; onExpand?: (verstr: string) => void;
}) {
  return (
    <>
      <div className="nest">
        {r.job && onExpand && <TreeToggle label={r.name || r.verstr} expanded={expanded} onToggle={() => onExpand(r.verstr)} />}
        <Link className={`run-link${r.name ? " run-name" : " mono"}`} to={href} title={r.verstr}>
          {r.name || r.verstr}
        </Link>
        <MatchingRunsChip r={r} runBase={ctx.runBase} search={ctx.search} />
        <AttentionChips r={r} ctx={ctx} />
        <BaselineCell r={r} ctx={ctx} />
        {compact && <span className="job-inline"><JobSubLine r={r} inline /></span>}
      </div>
      {!compact && <div className="exp-branch job-line"><JobSubLine r={r} /></div>}
    </>
  );
}

function JobRow({ r, index, isActive, isSelected, density, ctx, onToggle, expanded = false, onExpand }: {
  r: ExperimentRow; index: number;
  /** The table's one tab stop (roving tabindex). */
  isActive: boolean; isSelected: boolean;
  density?: Density; ctx: JobContext;
  onToggle: (verstr: string, range: boolean) => void;
  /** Whether its tree is open under it, and what opens or folds it (plan 28 N6). */
  expanded?: boolean;
  onExpand?: (verstr: string) => void;
}) {
  const href = runHref(ctx.runBase, r.verstr);
  const numbers = jobNumbers(r);
  const when = jobWhen(r);
  const status = headStatus(r);
  const onClick = useRowNavigate(href);

  const body = (id: string) => {
    switch (id) {
      case "check":
        return (
          <RowCheckbox verstr={r.verstr} checked={isSelected} onToggle={onToggle} />
        );
      case "idx": return `@${r.idx}`;
      case "status":
        return status && (
          <StatusPill
            status={status} exitCode={r.exit_code} durationSec={r.duration_sec}
            staleSec={r.stale_sec} errorSummary={r.error_summary} lost={r.job?.lost}
          />
        );
      case "name":
        return <NameCell r={r} href={href} compact={density === "compact"} ctx={ctx} expanded={expanded} onExpand={onExpand} />;
      case "value": return <ValueCell r={r} ctx={ctx} />;
      case "spread": return <SpreadCell r={r} />;
      case "runs": case "failed": case "rate": case "throughput": case "eta": return numbers[id].text;
      case "branch": return r.branch;
      case "when": return jobWhenText(when);
    }
    return null;
  };

  return (
    <tr
      style={{ height: densityRowHeight(density) }}
      className={`row job-row${isSelected ? " checked" : ""}${r.archived ? " archived" : ""}`}
      data-row-index={index} data-href={href} tabIndex={isActive ? 0 : -1}
      onClick={onClick}
    >
      {JOB_COLUMNS.map((c, i) => (
        <td
          key={c.id} data-col-id={c.id} style={COLUMN_STYLES[i]} className={CELL_CLASSES[i]}
          title={titleOf(c.id, when, numbers)}
        >
          {body(c.id)}
        </td>
      ))}
    </tr>
  );
}

export default memo(JobRow);
