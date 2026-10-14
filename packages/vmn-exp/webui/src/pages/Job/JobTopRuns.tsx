/** The job's top 10 runs on its main metric (plan 23 §3.2), linked, plus
 *  the way to all of them (the Runs tab). */
import { Link } from "react-router-dom";
import type { JobTopRun } from "../../apiJob";
import StatusPill from "../../components/StatusPill";
import { fmtVal, runHref } from "../../util";

/** Why there is no top: no metric at all, no goal to rank on, or no value yet. */
function emptyText(metric: string | null, ranked: boolean): string {
  if (!metric) return "No run in this outer run logged a metric yet.";
  if (!ranked) {
    return `No goal declared for ${metric} — runs aren't ranked. Declare one with `
      + `experiment.metrics.${metric}.goal or run.define_metric(goal=...)`;
  }
  return "No run has a value to rank yet.";
}

export default function JobTopRuns({ top, metric, ranked = true, appBase, allHref }: {
  top: JobTopRun[]; metric: string | null; ranked?: boolean; appBase: string; allHref: string;
}) {
  if (!metric || !ranked || !top.length) return <p className="muted job-empty">{emptyText(metric, ranked)}</p>;
  return (
    <>
      <table className="job-top" aria-label={`Top runs on ${metric}`}>
        <thead>
          <tr><th scope="col">#</th><th scope="col">run</th><th scope="col">status</th><th scope="col" className="num">{metric}</th></tr>
        </thead>
        <tbody>
          {top.map((r, i) => (
            <tr key={r.verstr}>
              <td className="muted">{i + 1}</td>
              <td>
                <Link className="run-link" to={runHref(appBase, r.verstr)} title={r.verstr}>
                  <span className="mono">{r.idx != null ? `@${r.idx}` : r.verstr}</span>
                  {r.name && <>{" "}<span className="run-name">{r.name}</span></>}
                </Link>
              </td>
              <td><StatusPill status={r.status} /></td>
              <td className="num mono">{fmtVal(r.value)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <Link className="job-more" to={allHref}>Show all in Runs</Link>
    </>
  );
}
