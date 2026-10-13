/** The Overview's two fetched cards: the top failure clusters (W5's
 *  endpoint, shared with the Failures tab) and, for a sweep, the params
 *  that matter (importance scoped to the job). */
import { Link } from "react-router-dom";
import { plural } from "../../util";
import { barPercent } from "../../util/importanceData";
import { sharePct } from "./jobData";
import { useJobFailures, useJobImportance } from "./jobQueries";

const TOP_CLUSTERS = 3;

export function JobFailureTop({ ws, app, verstr, failed, failuresHref }: {
  ws: string; app: string; verstr: string; failed: number; failuresHref: string;
}) {
  const q = useJobFailures(ws, app, verstr, failed);
  if (q.error) return <p className="error" role="alert">{q.error.message}</p>;
  if (!q.data) return <div className="skeleton" aria-label="loading"><div className="line" /></div>;
  if (!q.data.clusters.length) return <p className="job-good">No failures.</p>;
  return (
    <ul className="job-cluster-top">
      {q.data.clusters.slice(0, TOP_CLUSTERS).map((c) => (
        <li key={c.sig}>
          <Link to={failuresHref} title={c.sig}>{c.label}</Link>
          <span className="muted"> {plural(c.count, "run")} · {sharePct(c.share)}%</span>
        </li>
      ))}
    </ul>
  );
}

export function JobImportance({ ws, app, verstr, metric, done }: {
  ws: string; app: string; verstr: string; metric: string | null; done: number;
}) {
  const q = useJobImportance(ws, app, verstr, metric, done);
  if (!metric) return null;
  if (q.error) return <p className="error" role="alert">{q.error.message}</p>;
  if (!q.data) return <div className="skeleton" aria-label="loading"><div className="line" /></div>;
  if (!q.data.length) return <p className="muted job-empty">Not enough finished runs to rank params yet.</p>;
  const top = q.data[0].importance;
  return (
    <ul className="job-importance" aria-label={`Params that matter for ${metric}`}>
      {q.data.map((e) => (
        <li key={e.param}>
          <span className="mono job-imp-name">{e.param}</span>
          <span
            className="job-imp-track" role="meter" aria-label={`${e.param} importance`}
            aria-valuemin={0} aria-valuemax={1} aria-valuenow={e.importance}
          >
            <span className="job-imp-bar" style={{ width: `${barPercent(e.importance, top)}%` }} />
          </span>
          <span className="mono muted job-imp-val">{e.importance.toFixed(2)}</span>
        </li>
      ))}
    </ul>
  );
}
