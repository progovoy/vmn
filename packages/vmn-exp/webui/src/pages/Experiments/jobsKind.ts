/** Which top-level runs the Jobs view lists (plan 23 §3.1): the jobs or
 *  the single runs, so thousands of single runs never bury the jobs.
 *  `kind=jobs|singles` in the URL, else the jobs when the app has any. An
 *  app whose facets count single runs and no jobs is *singles-only*: it
 *  lists them on the runs board (plan 38 A6). Any other app without jobs
 *  (facets that never answer, lack the counts or count no runs) lists every
 *  top-level run. Neither has a switch: both read like single runs. */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useUrlState } from "../../hooks/useUrlState";
import { facetsQuery } from "../../queries";
import type { ExperimentFacets, TopRuns } from "../../types";

export type JobsKind = "jobs" | "singles";

const asKind = (v: string | null): JobsKind | null => (v === "jobs" || v === "singles" ? v : null);

const hasJobs = (f: ExperimentFacets | undefined) => Boolean(f && f.jobs > 0);
const onlySingles = (f: ExperimentFacets | undefined) => Boolean(f && f.jobs === 0 && f.singles > 0);

export function useJobsKind(ws: string, app: string) {
  const client = useQueryClient();
  const facets = useQuery(facetsQuery(ws, app), client);
  const { params } = useUrlState();
  const urlKind = asKind(params.get("kind"));
  const known = facets.data !== undefined || facets.isError || facets.errorUpdatedAt > 0;
  const jobs = hasJobs(facets.data);
  const singlesOnly = onlySingles(facets.data);
  const kind: JobsKind | null = jobs ? urlKind ?? "jobs" : null;
  // Not known yet: the URL's side at once, else wait (null fetches nothing).
  const top: TopRuns | null = jobs ? kind : singlesOnly ? "singles" : known ? true : urlKind;
  const f = facets.data;
  const counts = f ? { jobs: f.jobs, singles: f.singles } : null;
  return { kind, top, counts, singlesOnly };
}

export type JobsKindState = ReturnType<typeof useJobsKind>;

/** The noun of what the view lists. */
export const kindNoun = (kind: JobsKind | null) =>
  kind === "jobs" ? "outer run" : kind === "singles" ? "single run" : "top-level run";

/** The `vmn-exp list --query` selecting the same rows. */
export const kindQuery = (kind: JobsKind | null) =>
  kind === "jobs" ? 'depth = 0 and kind = "outer"' : kind === "singles" ? 'kind = "single"' : "depth = 0";
