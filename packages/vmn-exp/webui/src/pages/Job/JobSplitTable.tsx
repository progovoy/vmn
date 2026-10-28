/** The Overview's tiles split by a tag or param (plan 28 P3): a small table
 *  under the KPI tiles, one row per value of `summary.split`, so a refit
 *  backlog shows beside thousands of done trials. */
import { Link } from "react-router-dom";
import type { JobPageSummary } from "../../apiJob";
import { SPLIT_COLUMNS, splitCells, type SplitCell } from "./jobSplit";

function Cell({ cell }: { cell: SplitCell }) {
  if (!cell.href) return <>{cell.text}</>;
  return <Link to={cell.href} aria-label={cell.label}>{cell.text}</Link>;
}

export default function JobSplitTable({ summary, runBase }: { summary: JobPageSummary; runBase: string }) {
  const { split, by } = summary;
  if (!split || !by?.length) return null;
  return (
    <table className="job-split" aria-label={`Runs by ${split}`}>
      <thead>
        <tr>
          <th scope="col" className="mono">{split}</th>
          {SPLIT_COLUMNS.map((name) => <th key={name} scope="col" className="num">{name}</th>)}
        </tr>
      </thead>
      <tbody>
        {by.map((entry) => (
          <tr key={entry.other ? "\u0000other" : entry.key ?? ""} className={entry.other ? "muted" : undefined}>
            {splitCells(entry, runBase).map((cell, i) => (
              <td key={i} className={i ? "num" : "mono"}><Cell cell={cell} /></td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
