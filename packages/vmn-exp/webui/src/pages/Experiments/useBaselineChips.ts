/** The Outer runs view's baseline chips (plan 28 N3): the loaded outer runs'
 *  chips in one request (`experiments-baselines?v=`, 200 runs a request),
 *  not one per row, refetched as their done counts move. Computed from the
 *  index (a settled pair once per server process), so it waits on no
 *  per-run store read. */
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { baselineChips } from "../../apiBaseline";
import { withSignal } from "../../requestScope";
import type { ExperimentRow } from "../../types";

export function useBaselineChips(ws: string, app: string, rows: readonly ExperimentRow[]) {
  const jobs = useMemo(() => rows.filter((r) => r.job).map((r) => r.verstr), [rows]);
  const done = rows.reduce((n, r) => n + (r.job?.done ?? 0), 0);
  return useQuery({
    queryKey: ["baseline-chips", ws, app, jobs, done],
    queryFn: ({ signal }) => withSignal(signal, () => baselineChips(ws, app, jobs)),
    enabled: jobs.length > 0,
    placeholderData: keepPreviousData,
    retry: false,
  }).data;
}
