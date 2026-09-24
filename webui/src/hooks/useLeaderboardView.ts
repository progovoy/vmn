import { useCallback, useMemo } from "react";
import { useUrlState } from "./useUrlState";

export const CHART_VIEWS = ["trend", "bar", "scatter", "parallel", "grouped"] as const;
export type ChartView = (typeof CHART_VIEWS)[number];
export type Order = "asc" | "desc";

/** The leaderboard's whole view — sort, filters, chart, hidden columns and
 *  selection — read from and written to the URL, so it is bookmarkable and
 *  Back returns to exactly what was on screen. */
export function useLeaderboardView() {
  const { params, update, setParam } = useUrlState();
  const read = (k: string) => params.get(k) ?? "";
  const order = params.get("order");

  const view = {
    sort: params.get("sort") || null,
    order: order === "asc" || order === "desc" ? (order as Order) : undefined,
    status: read("status"),
    query: read("q"),
    search: read("search"),
    branch: read("branch"),
    chart: (CHART_VIEWS as readonly string[]).includes(read("view"))
      ? (read("view") as ChartView) : "trend",
    creating: params.get("new") === "1",
  };

  const hiddenKey = params.getAll("hide").join("\u0000");
  const hidden = useMemo(() => new Set(hiddenKey ? hiddenKey.split("\u0000") : []), [hiddenKey]);
  const selKey = params.getAll("sel").join("\u0000");
  const selected = useMemo(() => new Set(selKey ? selKey.split("\u0000") : []), [selKey]);

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
        p.delete(name);
        const next = cur.includes(value) ? cur.filter((v) => v !== value) : [...cur, value];
        next.forEach((v) => p.append(name, v));
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
  }), [setParam, toggleIn]);

  return { ...view, hidden, selected, clickSort, ...setters };
}
