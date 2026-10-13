/** The job Charts tab's queries and its URL state (plan 23 W4):
 *  `?chart=scatter|parallel|curves|bypar&x=&y=&color=&k=`. */
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { jobColumns, jobFacets, jobTopRuns } from "../../apiJobCharts";
import { useUrlState } from "../../hooks/useUrlState";
import { withSignal } from "../../requestScope";
import { JOB_CHARTS, type JobChart } from "./jobChartData";
import { jobPrefix } from "./jobQueries";

/** The job's param/metric vocabulary; it moves as runs finish (*done*). */
export function useJobFacets(ws: string, app: string, v: string, done: number) {
  return useQuery({
    queryKey: [...jobPrefix(ws, app, v), "facets", done],
    queryFn: ({ signal }) => withSignal(signal, () => jobFacets(ws, app, v)),
    placeholderData: keepPreviousData,
  }, useQueryClient());
}

const COLUMNS_GC_MS = 30_000;

/** Columns *keys* over the job, refetched once more of its runs are *done*. */
export function useJobColumns(ws: string, app: string, v: string, keys: string[], done: number) {
  return useQuery({
    queryKey: [...jobPrefix(ws, app, v), "columns", keys, done],
    queryFn: ({ signal }) => withSignal(signal, () => jobColumns(ws, app, v, keys)),
    enabled: keys.length > 0,
    placeholderData: keepPreviousData,
    // Each `done` is a new entry of up to 50k runs: don't keep the old ones around.
    gcTime: COLUMNS_GC_MS,
  }, useQueryClient());
}

/** The best *k* runs on *metric*, when the summary's top ones are too few. */
export function useJobTopRuns(ws: string, app: string, v: string, metric: string, k: number, enabled: boolean, done: number) {
  return useQuery({
    queryKey: [...jobPrefix(ws, app, v), "top", metric, k, done],
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
