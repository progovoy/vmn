import { useMemo } from "react";
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import type { RowsFilter } from "../queries";
import type { ExperimentRow } from "../types";
import { chartKeys, columnsToRows } from "../util/chartColumns";
import type { ChartView } from "./useLeaderboardView";

/** Most runs a chart asks the server for in one go. */
export const CHART_ROW_LIMIT = 10_000;

/** What the leaderboard charts plot: every run the filter matches (only the
 *  keys the current chart needs), or — on a server without the columns
 *  endpoint, or until it answers — the rows the table has loaded. */
export function useChartRows(
  ws: string, app: string, filter: RowsFilter, view: ChartView,
  metricCols: string[], paramCols: string[], loaded: ExperimentRow[], total: number,
) {
  const client = useQueryClient();
  const keys = useMemo(() => chartKeys(view, metricCols, paramCols), [view, metricCols, paramCols]);
  const q = useQuery({
    // `total` rides along so a new run on a poll refreshes the chart.
    queryKey: ["experiments-columns", ws, app, filter, keys, total],
    queryFn: () => api.experimentsColumns(ws, app, keys, { ...filter, limit: CHART_ROW_LIMIT }),
    // With every run already loaded there is nothing more to fetch.
    enabled: keys.length > 0 && loaded.length < total,
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  }, client);

  const full = useMemo(() => (q.data ? columnsToRows(q.data) : null), [q.data]);
  if (full && !q.isError) {
    return { rows: full, label: `charting ${full.length} of ${q.data!.total} runs` };
  }
  return { rows: loaded, label: `charting the loaded ${loaded.length} of ${total}` };
}
