/** The job page's queries, keyed under one prefix per job, and its tab,
 *  kept in `?tab=`. */
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { jobFailures, jobImportance, jobSummary } from "../../apiJob";
import { useUrlState } from "../../hooks/useUrlState";
import { withSignal } from "../../requestScope";

export const jobPrefix = (ws: string, app: string, v: string) => ["job", ws, app, v] as const;

/** The rollup, the one query a live change refreshes; the costlier views
 *  below key on the rollup count they follow, so they refetch only once it moves. */
export const jobSummaryKey = (ws: string, app: string, v: string) => [...jobPrefix(ws, app, v), "summary"];

/** *split*: the page's `?split=` (plan 28 P3), else the server's default. */
export const jobSummaryQuery = (ws: string, app: string, v: string, split?: string | null) => ({
  queryKey: split ? [...jobSummaryKey(ws, app, v), split] : jobSummaryKey(ws, app, v),
  queryFn: ({ signal }: { signal: AbortSignal }) =>
    withSignal(signal, () => (split ? jobSummary(ws, app, v, split) : jobSummary(ws, app, v))),
});

/** Clusters of the job's *failed* (failed + stuck) runs. */
export function useJobFailures(ws: string, app: string, v: string, failed: number) {
  return useQuery({
    queryKey: [...jobPrefix(ws, app, v), "failures", failed],
    placeholderData: keepPreviousData,
    queryFn: ({ signal }) => withSignal(signal, () => jobFailures(ws, app, v)),
  }, useQueryClient());
}

/** Importance of the params on *metric* over the job's *done* runs. */
export function useJobImportance(ws: string, app: string, v: string, metric: string | null, done: number) {
  return useQuery({
    queryKey: [...jobPrefix(ws, app, v), "importance", metric, done],
    queryFn: ({ signal }) => withSignal(signal, () => jobImportance(ws, app, v, metric!)),
    enabled: !!metric,
    placeholderData: keepPreviousData,
  }, useQueryClient());
}

export const JOB_TABS = ["overview", "runs", "charts", "failures", "code", "log"] as const;
export type JobTab = typeof JOB_TABS[number];

export const JOB_TAB_LABELS: Record<JobTab, string> = {
  overview: "Overview", runs: "Runs", charts: "Charts", failures: "Failures", code: "Code", log: "Log",
};

const isTab = (t: string | null): t is JobTab => JOB_TABS.includes(t as JobTab);

/** `?tab=`, Overview when absent or unknown. */
export function useJobTab(): [JobTab, (tab: JobTab) => void] {
  const { params, setParam } = useUrlState();
  const raw = params.get("tab");
  return [isTab(raw) ? raw : "overview", (tab) => setParam("tab", tab)];
}

/** A link to tab *tab* of job *v* (with extra query params). */
export function jobTabHref(runBase: string, tab: JobTab, extra: Record<string, string> = {}) {
  return `${runBase}?${new URLSearchParams({ tab, ...extra })}`;
}
