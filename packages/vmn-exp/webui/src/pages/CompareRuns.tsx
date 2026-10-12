import { Link, useParams } from "react-router-dom";
import { useQueries, useQueryClient } from "@tanstack/react-query";
import { appName as toAppName } from "../api";
import { runQuery, useMetricsSchema } from "../queries";
import { setAllParams, useUrlState } from "../hooks/useUrlState";
import { PageHead } from "../components/ui";
import CompareRunsTable from "./CompareRunsTable";
import { MAX_COMPARE_RUNS, parseSelection, runLabel } from "./compareRunsData";
import type { ExperimentDetail } from "../types";

const diffHref = (base: string, v: string, to: string) =>
  `${base}/compare?v=${encodeURIComponent(v)}&to=${encodeURIComponent(to)}`;

/** Code-diff links for each adjacent pair of the selection. */
function PairLinks({ verstrs, details, base }: {
  verstrs: string[]; details: (ExperimentDetail | undefined)[]; base: string;
}) {
  return (
    <div className="toolbar compare-pairs">
      {verstrs.slice(1).map((to, i) => (
        <Link key={to} to={diffHref(base, verstrs[i], to)} title="code diff between these two runs">
          code diff: {runLabel(verstrs[i], details[i])} → {runLabel(to, details[i + 1])}
        </Link>
      ))}
    </div>
  );
}

/** Params and metrics of 2..50 selected runs side by side (`?sel=...`). */
export default function CompareRuns() {
  const { ws, app } = useParams() as { ws: string; app: string };
  const base = `/ws/${ws}/app/${app}`;
  const client = useQueryClient();
  const { params, update, setParam } = useUrlState();
  const { verstrs, dropped } = parseSelection(params);
  const onlyDiffering = params.get("diff") === "1";
  const schema = useMetricsSchema(ws, app);
  const results = useQueries({ queries: verstrs.map((v) => runQuery(ws, app, v)) }, client);
  const failed = results.flatMap((r, i) => (r.error ? [verstrs[i]] : []));
  const failedSet = new Set(failed);

  // Filter out unknown/failed refs from the table columns
  const validVerstrs = verstrs.filter((v) => !failedSet.has(v));
  const validDetails = results.filter((_, i) => !failedSet.has(verstrs[i])).map((r) => r.data);

  const onRemove = (verstr: string) =>
    update((p) => setAllParams(p, "sel", p.getAll("sel").filter((v) => v !== verstr)));

  return (
    <>
      <Link className="back-link" to={base}>← experiments</Link>
      <PageHead title="Compare runs" what={toAppName(app)} mono={false} />
      {verstrs.length < 2 ? (
        <div className="empty">
          Select at least two runs on the leaderboard to compare them side by side.
        </div>
      ) : (
        <>
          <p className="page-sub">
            {validVerstrs.length} runs side by side
            {dropped > 0 && ` · showing the first ${MAX_COMPARE_RUNS} (${dropped} more selected)`}
          </p>
          {failed.length > 0 && (
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 8 }}>
              {failed.map((ref) => (
                <span key={ref} className="badge" style={{ background: "var(--bad-bg, var(--line))" }}>
                  not found: <span className="mono">{ref}</span>{" "}
                  <button
                    className="link" aria-label={`remove ${ref}`} title="remove unknown ref"
                    onClick={() => onRemove(ref)}
                    style={{ marginLeft: 4 }}
                  >
                    remove
                  </button>
                </span>
              ))}
            </div>
          )}
          <div className="toolbar">
            <button
              aria-pressed={onlyDiffering}
              className={onlyDiffering ? "primary" : ""}
              onClick={() => setParam("diff", onlyDiffering ? "" : "1")}
            >
              Only differing
            </button>
          </div>
          {validVerstrs.length >= 2 && (
            <>
              <CompareRunsTable
                verstrs={validVerstrs} details={validDetails} schema={schema} base={base}
                onlyDiffering={onlyDiffering} onRemove={onRemove}
              />
              <PairLinks verstrs={validVerstrs} details={validDetails} base={base} />
            </>
          )}
        </>
      )}
    </>
  );
}
