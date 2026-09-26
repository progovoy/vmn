import { useCallback, useMemo } from "react";
import { setAllParams, useUrlState } from "./useUrlState";
import { moveKey, togglePin as togglePinUtil } from "../util/columnOrder";

export const CHART_VIEWS = ["trend", "bar", "scatter", "parallel", "grouped"] as const;
export type ChartView = (typeof CHART_VIEWS)[number];
export type Order = "asc" | "desc";

/** The leaderboard's whole view — sort, filters, chart, hidden columns,
 *  column order, pinning and selection — read from and written to the URL,
 *  so it is bookmarkable and Back returns to exactly what was on screen. */
export function useLeaderboardView() {
  const { params, update, setParam } = useUrlState();
  const read = (k: string) => params.get(k) ?? "";
  const sortOrder = params.get("order");

  const view = {
    sort: params.get("sort") || null,
    order: sortOrder === "asc" || sortOrder === "desc" ? (sortOrder as Order) : undefined,
    status: read("status"),
    query: read("q"),
    search: read("search"),
    branch: read("branch"),
    chart: (CHART_VIEWS as readonly string[]).includes(read("view"))
      ? (read("view") as ChartView) : "trend",
    creating: params.get("new") === "1",
    archived: params.get("archived") === "1",
  };

  const hidden = useParamSet(params, "hide");
  const selected = useParamSet(params, "sel");
  const expanded = useParamSet(params, "expand");
  const collapsed = useParamSet(params, "collapse");

  // Column order (col=) and pinned set (pin=) — stable arrays for useMemo deps.
  const colOrder = useParamList(params, "col");
  const pinned = useParamList(params, "pin");

  /** Sort by *col*; picking the sorted column again flips the direction.
   *  *best* is the direction the column's goal calls best-first. */
  const clickSort = useCallback(
    (col: string, best: Order) =>
      update((p) => {
        const flip = p.get("sort") === col;
        const cur = p.get("order") ?? best;
        p.set("sort", col);
        p.set("order", flip ? (cur === "asc" ? "desc" : "asc") : best);
      }),
    [update],
  );

  const toggleIn = useCallback(
    (name: string, value: string) =>
      update((p) => {
        const cur = p.getAll(name);
        setAllParams(p, name, cur.includes(value) ? cur.filter((v) => v !== value) : [...cur, value]);
      }),
    [update],
  );

  const setAll = useCallback(
    (name: string, values: readonly string[]) =>
      update((p) => setAllParams(p, name, values)),
    [update],
  );

  /** Flip a sweep open/shut; the URL records only departures from its
   *  default (big sweeps start collapsed). */
  const toggleCollapsed = useCallback(
    (verstr: string, collapsedByDefault: boolean) =>
      update((p) => {
        const drop = (name: string) => setAllParams(p, name, p.getAll(name).filter((v) => v !== verstr));
        const shut = p.getAll("collapse").includes(verstr) ||
          (collapsedByDefault && !p.getAll("expand").includes(verstr));
        drop("collapse");
        drop("expand");
        if (shut && collapsedByDefault) p.append("expand", verstr);
        if (!shut && !collapsedByDefault) p.append("collapse", verstr);
      }),
    [update],
  );

  const setters = useMemo(() => ({
    setStatus: (csv: string) => setParam("status", csv),
    setQuery: (q: string) => setParam("q", q),
    setSearch: (s: string) => setParam("search", s),
    setBranch: (b: string) => setParam("branch", b),
    setChart: (c: ChartView) => setParam("view", c === "trend" ? "" : c),
    openCreate: (open: boolean) => setParam("new", open ? "1" : ""),
    toggleHidden: (col: string) => toggleIn("hide", col),
    toggleSelected: (verstr: string) => toggleIn("sel", verstr),
    setSelected: (verstrs: readonly string[]) => setAll("sel", verstrs),
    setArchived: (on: boolean) => setParam("archived", on ? "1" : ""),
    setOrder: (keys: readonly string[]) => setAll("col", keys),
    moveColumn: (key: string, delta: number, defaultKeys: readonly string[]) =>
      update((p) => {
        const cur = p.getAll("col");
        const cur2 = p.getAll("pin");
        setAllParams(p, "col", moveKey(cur, key, delta, defaultKeys, cur2));
      }),
    togglePin: (key: string) =>
      update((p) => {
        const cur = p.getAll("pin");
        setAllParams(p, "pin", togglePinUtil(cur, key));
      }),
  }), [setParam, toggleIn, setAll, update]);

  return {
    ...view,
    hidden, selected, expanded, collapsed,
    colOrder, pinned,
    clickSort, toggleCollapsed, ...setters,
  };
}

/** A repeated query param as an ordered array, stable while its values are. */
function useParamList(params: URLSearchParams, name: string): readonly string[] {
  const key = params.getAll(name).join("\u0000");
  return useMemo(() => (key ? key.split("\u0000") : []), [key]);
}

/** A repeated query param as a set, stable while its values are. */
function useParamSet(params: URLSearchParams, name: string): ReadonlySet<string> {
  const list = useParamList(params, name);
  return useMemo(() => new Set(list), [list]);
}
