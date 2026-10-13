import { Link } from "react-router-dom";
import { useQueries, useQueryClient } from "@tanstack/react-query";
import { runQuery, useMetricsSchema } from "../../queries";
import { useUrlState } from "../../hooks/useUrlState";
import CompareRunsTable from "../CompareRunsTable";
import { MAX_COMPARE_RUNS, runLabel } from "../compareRunsData";
import type { ExperimentDetail } from "../../types";
import { compareSearch } from "./selection";

/** Code-diff links for each adjacent pair of the selection. */
function PairLinks({ verstrs, details, base }: {
  verstrs: string[]; details: (ExperimentDetail | undefined)[]; base: string;
}) {
  return (
    <div className="toolbar compare-pairs">
      {verstrs.slice(1).map((to, i) => (
        <Link key={to} to={`${base}/compare-runs?${compareSearch("code", [verstrs[i], to])}`}
          title="code diff between these two runs">
          code diff: {runLabel(verstrs[i], details[i])} → {runLabel(to, details[i + 1])}
        </Link>
      ))}
    </div>
  );
}

/** Params and metrics of 2..50 selected runs side by side. Unknown refs get
 *  no column; the selection chips mark them. */
export default function TableTab({ ws, app, refs }: { ws: string; app: string; refs: string[] }) {
  const base = `/ws/${ws}/app/${app}`;
  const client = useQueryClient();
  const { params, setParam } = useUrlState();
  const verstrs = refs.slice(0, MAX_COMPARE_RUNS);
  const dropped = refs.length - verstrs.length;
  // On by default (plan 20 M2): only `?diff=0` turns it off.
  const onlyDiffering = params.get("diff") !== "0";
  const schema = useMetricsSchema(ws, app);
  const results = useQueries({ queries: verstrs.map((v) => runQuery(ws, app, v)) }, client);
  const loaded = verstrs.flatMap((v, i) => (results[i].error ? [] : [{ v, detail: results[i].data }]));
  const validVerstrs = loaded.map((r) => r.v);
  const validDetails = loaded.map((r) => r.detail);

  if (verstrs.length < 2) {
    return (
      <div className="empty">
        Select at least two runs on the leaderboard to compare them side by side.
      </div>
    );
  }
  return (
    <>
      <p className="page-sub">
        {validVerstrs.length} runs side by side
        {dropped > 0 && ` · showing the first ${MAX_COMPARE_RUNS} (${dropped} more selected)`}
      </p>
      <div className="toolbar">
        <button
          aria-pressed={onlyDiffering}
          className={onlyDiffering ? "primary" : ""}
          onClick={() => setParam("diff", onlyDiffering ? "0" : "")}
        >
          Only differing
        </button>
      </div>
      {validVerstrs.length >= 2 && (
        <>
          <CompareRunsTable
            verstrs={validVerstrs} details={validDetails} schema={schema} base={base}
            onlyDiffering={onlyDiffering}
          />
          <PairLinks verstrs={validVerstrs} details={validDetails} base={base} />
        </>
      )}
    </>
  );
}
