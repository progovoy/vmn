/** A `pivot` report panel (plan 28 N2): the pivot heatmap of the panel's
 *  runs (its query, or its pinned verstrs), within an outer run when it
 *  names a `scope`; a cell opens the board (or the outer run's Runs tab)
 *  filtered to its runs. */
import { useQuery } from "@tanstack/react-query";
import { pivot, type PivotParams } from "../apiPivot";
import PivotHeatmap from "../components/PivotHeatmap";
import { jobTabHref } from "../pages/Job/jobQueries";
import { appHref, runHref } from "../util";
import { verstrInQuery } from "../util/searchQuery";
import type { PanelSpec } from "./panelSpec";

export type PivotSpec = Extract<PanelSpec, { type: "pivot" }>;

/** The board query of the panel's runs. */
const runsQuery = (runs: PivotSpec["runs"]) => ("verstrs" in runs ? verstrInQuery(runs.verstrs) : runs.query);

export function pivotParams(spec: PivotSpec): PivotParams {
  const cell = spec.cell ?? "count";
  return {
    rows: spec.rows, cols: spec.cols, cell,
    ...(cell === "share" ? { match: spec.match } : {}),
    ...(cell === "agg" ? { metric: spec.metric, ...(spec.agg ? { agg: spec.agg } : {}) } : {}),
    q: runsQuery(spec.runs),
    ...(spec.scope ? { scope: spec.scope } : {}),
    ...("archived" in spec.runs && spec.runs.archived ? { archived: true } : {}),
  };
}

export default function PivotPanel({ ws, spec }: { ws: string; spec: PivotSpec }) {
  const params = pivotParams(spec);
  const q = useQuery({ queryKey: ["panel-pivot", ws, spec.app, params], queryFn: () => pivot(ws, spec.app, params) });
  if (q.error) return <p className="error" role="alert">{q.error.message}</p>;
  if (!q.data) return <div className="muted">Loading…</div>;
  const board = appHref(ws, spec.app);
  const hrefOf = (query: string) => (spec.scope
    ? jobTabHref(runHref(board, spec.scope), "runs", { q: query })
    : `${board}?${new URLSearchParams({ q: query })}`);
  return <PivotHeatmap pivot={q.data} rowsField={spec.rows} colsField={spec.cols} hrefOf={hrefOf} baseQuery={params.q} />;
}
