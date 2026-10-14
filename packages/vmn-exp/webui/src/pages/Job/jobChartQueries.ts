/** The job Charts tab's queries and its URL state (plan 23 W4):
 *  `?chart=scatter|parallel|curves|bypar&x=&y=&color=&k=`. */
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import type { JobPageSummary } from "../../apiJob";
import { jobColumns, jobFacets, jobTopRuns } from "../../apiJobCharts";
import { useUrlState } from "../../hooks/useUrlState";
import { facetsQuery } from "../../queries";
import { withSignal } from "../../requestScope";
import { JOB_CHARTS, type JobChart } from "./jobChartData";
import { jobPrefix } from "./jobQueries";

/** The job's param/metric vocabulary: the subtree's facets, the same cache
 *  entry as its Runs tab's (so a live change refreshes both). */
export function useJobFacets(ws: string, app: string, v: string) {
  return useQuery({
    ...facetsQuery(ws, app, { scope: v }),
    queryFn: ({ signal }) => withSignal(signal, () => jobFacets(ws, app, v)),
    placeholderData: keepPreviousData,
  }, useQueryClient());
}

type Progress = Pick<JobPageSummary, "done" | "expected">;

/** The share of the job a chart refetch waits for (each read is up to 50k runs). */
const REFETCH_SHARE = 0.05;

/** What the chart queries key on: *done* in steps of ~5% of the job, and
 *  once more when it is all done. */
export function chartProgressKey({ done, expected }: Progress): number | "all" {
  if (expected > 0 && done >= expected) return "all";
  return Math.floor(done / Math.max(1, Math.ceil(expected * REFETCH_SHARE)));
}

const COLUMNS_GC_MS = 30_000;

/** Columns *keys* over the job, refetched once ~5% more of its runs are done. */
export function useJobColumns(ws: string, app: string, v: string, keys: string[], progress: Progress) {
  return useQuery({
    queryKey: [...jobPrefix(ws, app, v), "columns", keys, chartProgressKey(progress)],
    queryFn: ({ signal }) => withSignal(signal, () => jobColumns(ws, app, v, keys)),
    enabled: keys.length > 0,
    placeholderData: keepPreviousData,
    // Each step is a new entry of up to 50k runs: don't keep the old ones around.
    gcTime: COLUMNS_GC_MS,
  }, useQueryClient());
}

/** The best *k* runs on *metric*, when the summary's top ones are too few. */
export function useJobTopRuns(
  ws: string, app: string, v: string, metric: string, k: number, enabled: boolean, progress: Progress,
) {
  return useQuery({
    queryKey: [...jobPrefix(ws, app, v), "top", metric, k, chartProgressKey(progress)],
    queryFn: ({ signal }) => withSignal(signal, () => jobTopRuns(ws, app, v, metric, k)),
    enabled,
    placeholderData: keepPreviousData,
  }, useQueryClient());
}

export const TOP_K = [5, 20, 50] as const;
const DEFAULT_K = 20;

export interface JobChartState {
  chart: JobChart;
  x: string | null;
  y: string | null;
  color: string | null;
  k: number;
  set: (patch: Partial<Record<"chart" | "x" | "y" | "color" | "k", string | null>>) => void;
}

const isChart = (c: string | null): c is JobChart => JOB_CHARTS.includes(c as JobChart);

export function useJobChartState(): JobChartState {
  const { params, update } = useUrlState();
  const chart = params.get("chart");
  const k = Number(params.get("k"));
  return {
    chart: isChart(chart) ? chart : "scatter",
    x: params.get("x"),
    y: params.get("y"),
    color: params.get("color"),
    k: (TOP_K as readonly number[]).includes(k) ? k : DEFAULT_K,
    set: (patch) => update((p) => {
      for (const [name, value] of Object.entries(patch)) {
        if (value) p.set(name, value); else p.delete(name);
      }
    }),
  };
}
