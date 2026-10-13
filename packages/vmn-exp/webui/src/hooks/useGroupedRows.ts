/** The grouped board's data (plan 22 K1, G4, G5): a page of groups through
 *  the request cache (under the app's rows, so edits and refreshes reach
 *  it), more groups on demand, and the rest of one group (`+N more`). */
import { useCallback, useRef, useState } from "react";
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import type { GroupAggregate, GroupField } from "../apiGroups";
import type { HttpError } from "../http";
import { isAbortError, withSignal } from "../requestScope";
import { rowsPrefix, type RowsFilter } from "../queries";
import { useShownList } from "./useShownList";
import { cacheOf, deeperGroups, withGroupRows, withGroups } from "../util/groupedCache";
import type { GroupedRows, MoreState } from "../util/groupItems";

/** Groups per page, and the server's cap on a page. */
const GROUPS_PAGE = 50;
const PAGE_MAX = 1000;

const clamp = (n: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, n));

const groupsKey = (
  ws: string, app: string, filter: RowsFilter, group: string | null, agg: GroupAggregate | undefined,
) => [...rowsPrefix(ws, app), "groups", group, agg ?? null, filter] as const;

/** *group* null: not grouped, nothing fetched. *agg* only when the URL
 *  names one; else the server applies the app's default. */
export function useGroupedRows(
  ws: string, app: string, filter: RowsFilter, group: string | null, agg: GroupAggregate | undefined,
) {
  const client = useQueryClient();
  const key = groupsKey(ws, app, filter, group, agg);
  const opts = { ...filter, group: (group ?? "") as GroupField, agg };
  const read = () => client.getQueryData<GroupedRows>(key);

  const query = useQuery<GroupedRows, HttpError>({
    queryKey: key,
    enabled: group !== null,
    // A refresh asks again for as many groups as are loaded, each group
    // then for as many rows as it held (its own `+N more` depth).
    queryFn: async ({ signal }) => {
      const cur = read();
      const page = await withSignal(signal, () => api.experimentGroups(ws, app, {
        ...opts, offset: 0, limit: clamp(cur?.groups.length ?? 0, GROUPS_PAGE, PAGE_MAX),
      }));
      const next = cacheOf(page);
      const deeper = await Promise.all(deeperGroups(cur, next).map(([key, offset, limit]) =>
        withSignal(signal, () => api.experimentGroupRows(ws, app, key, {
          ...opts, offset, limit: Math.min(limit, PAGE_MAX),
        }))));
      return deeper.reduce(withGroupRows, next);
    },
    placeholderData: keepPreviousData,
    structuralSharing: false,
  }, client);

  const { data, queryError, pageError } = useShownList(query, group !== null);
  // The aggregate an answer to no `agg=` names: the app's default (F3).
  const answeredDefault = useRef<GroupAggregate>();
  if (!agg && !query.isPlaceholderData && query.data?.aggregate) answeredDefault.current = query.data.aggregate;

  const [moreError, setMoreError] = useState<string | null>(null);
  const [more, setMore] = useState<ReadonlyMap<string, MoreState>>(new Map());
  const loading = useRef(false);
  const keyHash = JSON.stringify(key);

  const loadMore = useCallback(async () => {
    const cur = read();
    if (!cur || loading.current || cur.groups.length >= cur.total_groups) return;
    loading.current = true;
    try {
      const next = await api.experimentGroups(ws, app, { ...opts, offset: cur.groups.length, limit: GROUPS_PAGE });
      client.setQueryData<GroupedRows>(key, withGroups(read() ?? cur, next));
      setMoreError(null);
    } catch (e) {
      if (!isAbortError(e)) setMoreError(String(e));
    } finally {
      loading.current = false;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client, keyHash]);

  const loadGroup = useCallback(async (groupKey: string) => {
    const g = read()?.groups.find((x) => x.key === groupKey);
    if (!g) return;
    const mark = (s: MoreState | null) => setMore((m) => {
      const out = new Map(m);
      if (s) out.set(groupKey, s);
      else out.delete(groupKey);
      return out;
    });
    mark("loading");
    try {
      const offset = g.verstrs.length;
      const page = await api.experimentGroupRows(ws, app, groupKey, {
        ...opts, offset, limit: Math.min(g.rows_total - offset, PAGE_MAX),
      });
      const cur = read();
      if (cur) client.setQueryData<GroupedRows>(key, withGroupRows(cur, page));
      mark(null);
    } catch (e) {
      mark(isAbortError(e) ? null : "error");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client, keyHash]);

  const refresh = useCallback(() => query.refetch().then((r) => r.data), [query.refetch]);

  return {
    data,
    queryError, pageError,
    moreError, more, loadMore, loadGroup, refresh,
    defaultAggregate: answeredDefault.current,
    updatedAt: query.dataUpdatedAt,
  };
}
