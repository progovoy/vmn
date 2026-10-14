/** The facet sidebar's counts (plan 23 W3), from the §10 endpoints: status
 *  and param value counts are the grouped list's group sizes, a many-valued
 *  numeric param's values its `experiments-columns`. The status counts are
 *  keyed under the app's facets, so a live change refreshes them with the
 *  rest; a param's counts only follow the filtered facets' total and the
 *  param's distinct values, so a change that moved neither costs no
 *  request per param. */
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo } from "react";
import { api, type FacetOpts } from "../api";
import { useFacets } from "../queries";
import type { GroupField } from "../apiGroups";
import { MAX_PARAM_VALUES } from "../util/groupBy";
import { columnCounts, numericLike } from "../util/facetBins";

export interface ValueCount {
  key: string;
  count: number;
}

export interface ParamCounts {
  values: ValueCount[];
  /** Distinct values past the ones listed. */
  more: number;
  /** Every value when they are numbers too many to list (the histogram's). */
  numbers: unknown[] | null;
}

/** Drop empty filters, so equal filters share a cache entry and a request. */
const clean = (o: FacetOpts): FacetOpts =>
  Object.fromEntries(Object.entries(o).filter(([, v]) => v)) as FacetOpts;

const groupCounts = (ws: string, app: string, group: GroupField, opts: FacetOpts, limit: number) =>
  api.experimentGroups(ws, app, {
    group, ...opts, rowsPerGroup: 1, limit, ...(group === "status" ? {} : { sort: "c:total", order: "desc" }),
  });

/** The params worth a facet: the ones whose value varies across the runs
 *  the filters leave (the app's order). */
export function useFacetParams(ws: string, app: string, opts: FacetOpts): FacetParam[] {
  const facets = useFacets(ws, app, clean(opts));
  return useMemo(() => {
    const counts = facets?.param_values ?? {};
    const total = facets?.total ?? 0;
    return (facets?.param_keys ?? []).filter((k) => (counts[k] ?? 0) > 1)
      .map((key) => ({ key, many: counts[key] > MAX_PARAM_VALUES, moved: `${total}:${counts[key]}` }));
  }, [facets]);
}

export interface FacetParam {
  key: string;
  /** More distinct values than a facet lists (the facets cap the count past 20). */
  many: boolean;
  /** Moves when its counts may: the filtered runs' total and its distinct values. */
  moved: string;
}

/** A many-valued param's counts from its column, never its grouping: on a
 *  big job, grouping by a value almost every run has its own builds a group
 *  (with its aggregates) per run, and every facet queued behind it waits. */
async function fromColumn(ws: string, app: string, field: string, f: FacetOpts): Promise<ParamCounts> {
  const cols = await api.experimentsColumns(ws, app, [field], f);
  const column = cols.columns[field] ?? [];
  const { values, distinct } = columnCounts(column, MAX_PARAM_VALUES);
  if (numericLike(values.map((v) => v.key))) return { values: [], more: distinct, numbers: column };
  return { values, more: distinct - values.length, numbers: null };
}

/** Runs per status under the other filters (not the status filter itself). */
export function useStatusCounts(ws: string, app: string, opts: FacetOpts) {
  const f = clean({ ...opts, status: undefined });
  return useQuery({
    queryKey: ["facets", ws, app, "status", f],
    queryFn: () => groupCounts(ws, app, "status", f, 10)
      .then((p) => p.groups.map((g): ValueCount => ({ key: g.key, count: g.rows_total }))),
    placeholderData: keepPreviousData,
  }, useQueryClient());
}

/** *param*'s most common values (all of them up to 20), and with more
 *  numeric values than that, every value for a histogram. */
export function useParamCounts(ws: string, app: string, { key: param, many, moved }: FacetParam, opts: FacetOpts) {
  const f = clean(opts);
  const field = `params.${param}` as const;
  return useQuery({
    queryKey: ["facet-params", ws, app, param, f, moved],
    staleTime: Infinity,
    queryFn: async (): Promise<ParamCounts> => {
      if (many) return fromColumn(ws, app, field, f);
      const page = await groupCounts(ws, app, field, f, MAX_PARAM_VALUES);
      const values = page.groups.map((g) => ({ key: g.key, count: g.rows_total }));
      const more = Math.max(0, page.total_groups - values.length);
      if (!more || !numericLike(values.map((v) => v.key))) return { values, more, numbers: null };
      const cols = await api.experimentsColumns(ws, app, [field], f);
      return { values, more, numbers: cols.columns[field] ?? [] };
    },
    placeholderData: keepPreviousData,
  }, useQueryClient());
}
