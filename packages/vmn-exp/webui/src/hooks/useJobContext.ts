/** An inner run's job context (plan 23 W7): its job's rollup, its place in
 *  the order the job's Runs tab showed (`?from=&at=`, else the job's default
 *  order, placed by a count), its neighbours there and its rank on the job's
 *  main metric (a count of the runs better than it). */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { api } from "../api";
import { jobSummaryQuery } from "../pages/Job/jobQueries";
import { mainMetric } from "../pages/Job/jobData";
import { aheadClause, betterClause, decodeFrom, defaultOrder, type BoardOrder } from "../util/runContext";

const pageOpts = (o: BoardOrder) => ({ scope: o.scope, query: o.q, status: o.status, sort: o.sort, order: o.order });

/** How many runs of *scope* match *query*. */
const countOf = (ws: string, app: string, scope: string, query: string, extra: Partial<BoardOrder> = {}) =>
  api.experimentsPaged(ws, app, { scope, query, limit: 1, ...extra }).then((p) => p.total);

export function useJobContext({ ws, app, verstr, idx, job, metrics }: {
  ws: string; app: string; verstr: string; idx: number | null; job: string;
  metrics: Record<string, number | string | null>;
}) {
  const client = useQueryClient();
  const [params] = useSearchParams();
  const summary = useQuery(jobSummaryQuery(ws, app, job), client).data;

  const carried = decodeFrom(params.get("from"), job);
  const atParam = carried ? Number(params.get("at")) : NaN;
  const order = carried && Number.isInteger(atParam) ? carried : defaultOrder(job);
  const placed = useQuery({
    queryKey: ["job-context", ws, app, job, "ahead", idx],
    queryFn: () => countOf(ws, app, job, aheadClause(idx!), { sort: "idx" }),
    enabled: order !== carried && idx != null,
  }, client);
  const at = order === carried ? atParam : placed.data;

  const offset = at === undefined ? 0 : Math.max(0, at - 1);
  const around = useQuery({
    queryKey: ["job-context", ws, app, job, "window", order, offset],
    queryFn: () => api.experimentsPaged(ws, app, { ...pageOpts(order), offset, limit: 3 }),
    enabled: at !== undefined,
  }, client);
  const rows = around.data?.rows ?? [];
  const here = rows.findIndex((r) => r.verstr === verstr);

  const metric = summary ? mainMetric(summary) : null;
  const m = metric ? summary?.metrics[metric] : null;
  const value = metric ? metrics[metric] : null;
  // Ranked toward the summary's goal only, never a guessed one (plan 32 F5).
  const better = summary?.ranked !== false && metric && m?.goal && typeof value === "number" && Number.isFinite(value)
    ? betterClause(metric, value, m.goal) : null;
  const ahead = useQuery({
    queryKey: ["job-context", ws, app, job, "rank", better],
    queryFn: () => countOf(ws, app, job, better!),
    enabled: !!better,
  }, client);

  return {
    summary,
    order,
    place: here >= 0 && at !== undefined ? { at, total: around.data!.total } : null,
    prev: here > 0 ? { row: rows[here - 1], at: at! - 1 } : null,
    next: here >= 0 && here < rows.length - 1 ? { row: rows[here + 1], at: at! + 1 } : null,
    rank: better && ahead.data !== undefined && m ? { rank: ahead.data + 1, of: m.n, metric: metric! } : null,
    peers: metric && m && typeof value === "number" ? { metric, m, value } : null,
  };
}
