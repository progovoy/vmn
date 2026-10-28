/** The tree's state (plan 28 N6): which nodes the reader folded or opened,
 *  how many pages of each parent's children are asked for, and those
 *  pages, fetched lazily as nodes open (`experiments?children_of=`), under
 *  the *filter* given (keyed by it). A page starts where the loaded ones
 *  end; pages showing live runs refresh. */
import { useCallback, useRef, useState } from "react";
import { useQueries, useQueryClient } from "@tanstack/react-query";
import { fetchChildren, type TreeFilter, type TreePage } from "../apiTree";
import { itemKey, treeItems, type TreeItem, type TreePages } from "../util/treeItems";

const LIVE_REFRESH_MS = 15_000;

const NO_FILTER: TreeFilter = {};

const childrenKey = (ws: string, app: string, filter: TreeFilter, parent: string, offset: number) =>
  ["tree-children", ws, app, filter, parent, offset] as const;

const live = (page: TreePage | undefined) => Boolean(page?.rows.some((r) =>
  r.status === "running" || (r.job?.counts.running ?? 0) > 0));

export function useTreeChildren(ws: string, app: string, root: string, filter: TreeFilter = NO_FILTER) {
  const client = useQueryClient();
  const [overrides, setOverrides] = useState<ReadonlyMap<string, boolean>>(new Map());
  const [pageCounts, setPageCounts] = useState<ReadonlyMap<string, number>>(new Map());

  const cached = (parent: string, offset: number) =>
    client.getQueryData<TreePage>(childrenKey(ws, app, filter, parent, offset));
  /** The offsets of *parent*'s pages that can be asked for (each after a
   *  loaded one), found once per parent a render. */
  const offsetsOf = new Map<string, number[]>();
  const offsets = (parent: string) => {
    let out = offsetsOf.get(parent);
    if (out) return out;
    out = [0];
    for (let i = 1; i < (pageCounts.get(parent) ?? 1); i++) {
      const prev = cached(parent, out[i - 1]);
      if (!prev) break;
      out.push(out[i - 1] + prev.rows.length);
    }
    offsetsOf.set(parent, out);
    return out;
  };
  const pages: TreePages = {
    count: (parent) => pageCounts.get(parent) ?? 1,
    page: (parent, i) => {
      const at = offsets(parent)[i];
      return at === undefined ? undefined : cached(parent, at);
    },
  };
  const walked = treeItems(root, pages, overrides);
  const { wanted } = walked;
  const items = useStableItems(walked.items);

  const results = useQueries({
    queries: wanted.flatMap((parent) => offsets(parent).map((offset) => ({
      queryKey: childrenKey(ws, app, filter, parent, offset),
      queryFn: () => fetchChildren(ws, app, parent, { offset, filter }),
      refetchInterval: (q: { state: { data?: TreePage } }) => (live(q.state.data) ? LIVE_REFRESH_MS : false),
    }))),
  });
  const columns = results.find((r) => r.data?.tree_columns)?.data?.tree_columns;

  const toggle = useCallback((verstr: string, open: boolean) =>
    setOverrides((m) => new Map(m).set(verstr, open)), []);
  const more = useCallback((parent: string) =>
    setPageCounts((m) => new Map(m).set(parent, (m.get(parent) ?? 1) + 1)), []);
  const rows = items.flatMap((it) => (it.kind === "node" ? [it.row] : []));

  return { items, rows, columns, toggle, more };
}

const sameItem = (a: TreeItem, b: TreeItem) =>
  (Object.keys(a) as (keyof TreeItem)[]).every((k) => a[k] === b[k]);

/** *items*, each the previous render's object when nothing in it changed,
 *  so memoized rows skip a render that moved only the focus or another node. */
function useStableItems(items: TreeItem[]): TreeItem[] {
  const prev = useRef(new Map<string, TreeItem>());
  const next = new Map<string, TreeItem>();
  const out = items.map((it) => {
    const key = itemKey(it);
    const old = prev.current.get(key);
    const kept = old && sameItem(old, it) ? old : it;
    next.set(key, kept);
    return kept;
  });
  prev.current = next;
  return out;
}
