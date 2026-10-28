/** The Overview's pivot heatmap (plan 28 N2): the outer run's runs crossed
 *  by two fields picked from its facets (tags, params, their ancestors'),
 *  each cell a count, the share matching a query, or an aggregate of a
 *  metric; a cell opens the Runs tab filtered to its runs. The server keeps
 *  a settled outer run's pivot until its subtree changes. */
import { useState, type FormEvent } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { pivot, type PivotKind, type PivotParams } from "../../apiPivot";
import PivotHeatmap from "../../components/PivotHeatmap";
import { Skeleton } from "../../components/ui";
import { appHref, runHref } from "../../util";
import { defaultAxes, fieldOptions } from "../../util/pivotCells";
import { withSignal } from "../../requestScope";
import { ChartEmpty, Picker } from "./JobChartParts";
import { useJobFacets } from "./jobChartQueries";
import { jobPrefix, jobTabHref } from "./jobQueries";

const CELLS: PivotKind[] = ["count", "share", "agg"];
const CELL_NAMES: Record<string, string> = { count: "runs", share: "share matching", agg: "metric" };
const AGGREGATES = ["median", "mean", "min", "max", "best"];
const DEFAULT_MATCH = 'status = "failed"';

interface Props { ws: string; app: string; verstr: string; metrics: string[]; done: number }

function usePivot(ws: string, app: string, v: string, params: PivotParams | null, done: number) {
  return useQuery({
    queryKey: [...jobPrefix(ws, app, v), "pivot", params, done],
    queryFn: ({ signal }) => withSignal(signal, () => pivot(ws, app, params!)),
    enabled: !!params,
    placeholderData: keepPreviousData,
    retry: false,
  });
}

function MatchForm({ value, onApply }: { value: string; onApply: (q: string) => void }) {
  const [draft, setDraft] = useState(value);
  const submit = (e: FormEvent) => { e.preventDefault(); onApply(draft.trim() || DEFAULT_MATCH); };
  return (
    <form onSubmit={submit} className="job-picker">
      <label htmlFor="pivot-match">Matching</label>
      <input id="pivot-match" className="mono" value={draft} onChange={(e) => setDraft(e.target.value)} />
    </form>
  );
}

export default function JobPivot({ ws, app, verstr, metrics, done }: Props) {
  const facets = useJobFacets(ws, app, verstr);
  const fields = facets.data ? fieldOptions(facets.data) : [];
  const [axes, setAxes] = useState<[string | null, string | null]>([null, null]);
  const [cell, setCell] = useState<PivotKind>("count");
  const [match, setMatch] = useState(DEFAULT_MATCH);
  const [metric, setMetric] = useState<string | null>(null);
  const [agg, setAgg] = useState("median");
  const [defRows, defCols] = fields.length ? defaultAxes(fields) : [null, null];
  const rows = axes[0] ?? defRows, cols = axes[1] ?? defCols;
  const m = metric ?? metrics[0] ?? null;
  const params: PivotParams | null = rows && cols && (cell !== "agg" || m) ? {
    scope: verstr, rows, cols, cell,
    ...(cell === "share" ? { match } : {}), ...(cell === "agg" ? { metric: m!, agg } : {}),
  } : null;
  const query = usePivot(ws, app, verstr, params, done);
  if (facets.isError) return <p className="error" role="alert">{facets.error.message}</p>;
  if (!facets.data) return <Skeleton />;
  if (!rows || !cols) return null;
  const runBase = runHref(appHref(ws, app), verstr);
  return (
    <>
      <div className="pivot-tools">
        <Picker label="Rows" value={rows} options={fields} onChange={(v) => setAxes([v, cols])} />
        <Picker label="Columns" value={cols} options={fields} onChange={(v) => setAxes([rows, v])} />
        <Picker label="Cell" value={cell} options={CELLS} names={(c) => CELL_NAMES[c]} onChange={(c) => setCell(c as PivotKind)} />
        {cell === "share" && <MatchForm value={match} onApply={setMatch} />}
        {cell === "agg" && m && <Picker label="Metric" value={m} options={metrics} onChange={setMetric} />}
        {cell === "agg" && <Picker label="Aggregate" value={agg} options={AGGREGATES} onChange={setAgg} />}
      </div>
      {cell === "agg" && !m && <ChartEmpty text="No metric to aggregate yet." />}
      {query.isError && <p className="error" role="alert">{query.error.message}</p>}
      {!query.isError && query.data && (
        <PivotHeatmap pivot={query.data} rowsField={rows} colsField={cols}
          hrefOf={(q) => jobTabHref(runBase, "runs", { q })} />
      )}
      {!query.isError && !query.data && params && <Skeleton />}
    </>
  );
}
