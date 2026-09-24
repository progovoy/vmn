import { Link, useParams } from "react-router-dom";
import { useQueries } from "@tanstack/react-query";
import { appName as toAppName } from "../api";
import { useAppQueryClient } from "../queryClient";
import { runQuery, useMetricsSchema } from "../queries";
import { useUrlState } from "../hooks/useUrlState";
import { PageHead } from "../components/ui";
import CompareRunsTable from "./CompareRunsTable";
import { MAX_COMPARE_RUNS, parseSelection, runLabel, withoutRun } from "./compareRunsData";
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
  const client = useAppQueryClient();
  const { params, update, setParam } = useUrlState();
  const { verstrs, dropped } = parseSelection(params);
  const onlyDiffering = params.get("diff") === "1";
  const schema = useMetricsSchema(ws, app);
  const results = useQueries({ queries: verstrs.map((v) => runQuery(ws, app, v)) }, client);
  const details = results.map((r) => r.data);
  const failed = results.flatMap((r, i) => (r.error ? [verstrs[i]] : []));

  const onRemove = (verstr: string) =>
    update((p) => {
      const kept = withoutRun(p, verstr).getAll("sel");
      p.delete("sel");
      kept.forEach((v) => p.append("sel", v));
    });

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
            {verstrs.length} runs side by side
            {dropped > 0 && ` · showing the first ${MAX_COMPARE_RUNS} (${dropped} more selected)`}
          </p>
          <div className="toolbar">
            <button
              aria-pressed={onlyDiffering}
              className={onlyDiffering ? "primary" : ""}
              onClick={() => setParam("diff", onlyDiffering ? "" : "1")}
            >
              Only differing
            </button>
          </div>
          {failed.length > 0 && (
            <div className="error">could not load {failed.join(", ")}</div>
          )}
          <CompareRunsTable
            verstrs={verstrs} details={details} schema={schema} base={base}
            onlyDiffering={onlyDiffering} onRemove={onRemove}
          />
          <PairLinks verstrs={verstrs} details={details} base={base} />
        </>
      )}
    </>
  );
}
