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
    archived: params.get("archived") === "1",
  };

  const hidden = useParamSet(params, "hide");
  const selected = useParamSet(params, "sel");
  const expanded = useParamSet(params, "expand");
  const collapsed = useParamSet(params, "collapse");

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

  const setAll = useCallback(
    (name: string, values: readonly string[]) =>
      update((p) => {
        p.delete(name);
        values.forEach((v) => p.append(name, v));
      }),
    [update],
  );

  /** Flip a sweep open/shut; the URL records only departures from its
   *  default (big sweeps start collapsed). */
  const toggleCollapsed = useCallback(
    (verstr: string, collapsedByDefault: boolean) =>
      update((p) => {
        const drop = (name: string) => {
          const rest = p.getAll(name).filter((v) => v !== verstr);
          p.delete(name);
          rest.forEach((v) => p.append(name, v));
        };
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
  }), [setParam, toggleIn, setAll]);

  return {
    ...view, hidden, selected, expanded, collapsed, clickSort, toggleCollapsed, ...setters,
  };
}

/** A repeated query param as a set, stable while its values are. */
function useParamSet(params: URLSearchParams, name: string): ReadonlySet<string> {
  const key = params.getAll(name).join("\u0000");
  return useMemo(() => new Set(key ? key.split("\u0000") : []), [key]);
}
