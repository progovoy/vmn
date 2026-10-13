import { useCallback, useMemo } from "react";
import { useQueries, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { rowsPrefix, type RowsData, type RowsFilter } from "../queries";
import { SHARED_STALE_MS } from "../queryClient";
import type { ExperimentRow } from "../types";
import type { InnerRuns } from "../util/sweepTree";

/** The most inner runs one open outer lists (the list API's page cap). */
const INNER_PAGE_MAX = 1000;

type Scope = Pick<RowsFilter, "sort" | "order" | "archived">;
const innerKey = (ws: string, app: string, verstr: string, scope: Scope) =>
  [...rowsPrefix(ws, app), "inner", verstr, scope] as const;

function groupByParent(rows: readonly ExperimentRow[]): Map<string, ExperimentRow[]> {
  const out = new Map<string, ExperimentRow[]>();
  for (const r of rows) {
    if (!r.parent) continue;
    const list = out.get(r.parent);
    if (list) list.push(r);
    else out.set(r.parent, [r]);
  }
  return out;
}

/** The inner runs of every open outer: the loaded rows when they hold all of
 *  them, else one request per outer (`parent = "<verstr>"`, the board's sort,
 *  every status), cached under the app's rows so edits and refreshes reach it. */
export function useInnerRuns(
  ws: string, app: string, rows: readonly ExperimentRow[], expanded: ReadonlySet<string>, filter: RowsFilter,
) {
  const client = useQueryClient();
  const { sort, order, archived } = filter;
  const scope = useMemo<Scope>(() => ({ sort, order, archived }), [sort, order, archived]);
  const byParent = useMemo(() => groupByParent(rows), [rows]);
  const complete = useCallback(
    (r: ExperimentRow) => (byParent.get(r.verstr)?.length ?? 0) >= (r.children?.length ?? 0),
    [byParent],
  );
  const open = [...expanded];
  const cached = (v: string) => client.getQueryData<RowsData>(innerKey(ws, app, v, scope));

  // An open outer is fetched for once it is on screen: loaded, or among the
  // fetched inner runs of another open outer.
  const known = new Map(rows.map((r) => [r.verstr, r]));
  for (const v of open) for (const r of cached(v)?.rows ?? []) known.set(r.verstr, r);
  const childCount = (v: string) => known.get(v)?.children?.length ?? 0;
  const wanted = (v: string) => childCount(v) > 0 && !complete(known.get(v)!);

  const fetched = useQueries({
    queries: open.map((v) => ({
      queryKey: innerKey(ws, app, v, scope),
      queryFn: () => api.experimentsPaged(ws, app, {
        ...scope, query: `parent = "${v}"`, offset: 0,
        limit: Math.min(childCount(v), INNER_PAGE_MAX),
      }),
      enabled: wanted(v),
      staleTime: SHARED_STALE_MS,
    })),
    combine: (results) => new Map(open.map((v, i) => [v, results[i]] as const)),
  });

  const innerOf = useCallback((outer: ExperimentRow): InnerRuns => {
    if (complete(outer)) return { rows: byParent.get(outer.verstr) ?? [], more: 0 };
    const q = fetched.get(outer.verstr);
    if (q?.data) return { rows: q.data.rows, more: Math.max(0, q.data.total - q.data.rows.length) };
    return q?.isError ? "error" : "loading";
  }, [byParent, complete, fetched]);

  const refresh = useCallback(
    () => client.invalidateQueries({ queryKey: [...rowsPrefix(ws, app), "inner"] }),
    [client, ws, app],
  );
  return { innerOf, refresh };
}
