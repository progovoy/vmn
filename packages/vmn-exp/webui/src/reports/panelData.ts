/** Data hooks for report panels: a spec's runs, as rows or a single detail. */
import { useMemo } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { runKey, type RowsFilter } from "../queries";
import type { ExperimentDetail, ExperimentRow, MetricsSchema } from "../types";
import type { QueryRuns } from "./panelSpec";

/** How many runs a `curves` panel overlays when its query sets no limit. */
export const CURVES_RUN_LIMIT = 20;

/** Split spec keys (`params.lr`, `metrics.loss` or a bare metric) into the
 *  charts' metric and param columns. */
export function splitKeys(keys: string[]): { metricCols: string[]; paramCols: string[] } {
  const metricCols: string[] = [];
  const paramCols: string[] = [];
  for (const k of keys) {
    if (k.startsWith("params.")) paramCols.push(k.slice(7));
    else metricCols.push(k.startsWith("metrics.") ? k.slice(8) : k);
  }
  return { metricCols, paramCols };
}

/** The bare column name of a spec key. */
export const bareKey = (k: string) => k.replace(/^(params|metrics)\./, "");

export function queryFilter(runs: QueryRuns): RowsFilter {
  return { query: runs.query, sort: runs.sort, order: runs.order, archived: runs.archived };
}

export function useRunDetail(ws: string, app: string, verstr: string) {
  return useQuery({
    queryKey: runKey(ws, app, verstr),
    queryFn: () => api.experiment(ws, app, verstr),
  });
}

export function detailToRow(d: ExperimentDetail, i: number): ExperimentRow {
  const meta = d.metadata;
  return {
    ...d.status,
    idx: typeof meta.idx === "number" ? meta.idx : i + 1,
    verstr: meta.verstr,
    code_verstr: String(meta.code_verstr ?? meta.verstr),
    timestamp: (meta.timestamp as string | undefined) ?? null,
    note: (meta.note as string | undefined) ?? null,
    branch: (meta.branch as string | undefined) ?? null,
    base_version: null,
    params: d.params ?? {},
    metrics: d.metrics,
  };
}

/** Rows of pinned runs, from their details (shared with the run page's cache). */
export function usePinnedRows(ws: string, app: string, verstrs: string[]): ExperimentRow[] {
  const results = useQueries({
    queries: verstrs.map((v) => ({ queryKey: runKey(ws, app, v), queryFn: () => api.experiment(ws, app, v) })),
  });
  const details = results.map((r) => r.data);
  return useMemo(
    () => details.flatMap((d, i) => (d ? [detailToRow(d, i)] : [])),
    details, // eslint-disable-line react-hooks/exhaustive-deps
  );
}

/** Verstrs a query matches, best first per its sort, capped at its limit. */
export function useQueryVerstrs(ws: string, app: string, runs: QueryRuns): string[] {
  const filter = queryFilter(runs);
  const limit = runs.limit ?? CURVES_RUN_LIMIT;
  const q = useQuery({
    queryKey: ["panel-verstrs", ws, app, filter, limit],
    queryFn: () => api.experimentsPaged(ws, app, { ...filter, limit }),
  });
  return useMemo(() => (q.data?.rows ?? []).map((r) => r.verstr), [q.data]);
}

export function useSchema(ws: string, app: string): MetricsSchema | null {
  const q = useQuery({ queryKey: ["metrics-schema", ws, app], queryFn: () => api.metricsSchema(ws, app) });
  return q.data ?? null;
}
