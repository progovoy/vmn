import { useCallback, useMemo } from "react";
import { setAllParams, useUrlState } from "./useUrlState";
import { NO_PINS, moveKey, togglePin as togglePinUtil } from "../util/columnOrder";
import { parseAggregate, parseGroup, type Aggregate, type GroupBy } from "../util/groupBy";

export const CHART_VIEWS = ["trend", "bar", "scatter", "parallel", "grouped", "importance"] as const;
export type ChartView = (typeof CHART_VIEWS)[number];
export type Order = "asc" | "desc";
/** The board's view switcher: the runs table alone, or charts above it. */
export const BOARD_TABS = ["runs", "charts"] as const;
export type BoardTab = (typeof BOARD_TABS)[number];

const isChartView = (v: string | null): v is ChartView =>
  (CHART_VIEWS as readonly string[]).includes(v ?? "");

/** The open tab: `tab=` when set, else Charts for a URL that names a chart
 *  view (links from before the switcher), else Runs. */
function boardTab(p: URLSearchParams): BoardTab {
  const tab = p.get("tab");
  if (tab === "runs" || tab === "charts") return tab;
  return isChartView(p.get("view")) ? "charts" : "runs";
}

/** Write *tab* into *p*, leaving `tab=` out where the URL implies it anyway. */
function setBoardTab(p: URLSearchParams, tab: BoardTab) {
  p.delete("tab");
  if (boardTab(p) !== tab) p.set("tab", tab);
}

/** The leaderboard's whole view — sort, filters, tab, chart, hidden columns,
 *  column order, pinning and selection — read from and written to the URL,
 *  so it is bookmarkable and Back returns to exactly what was on screen. */
export function useLeaderboardView() {
  const { params, update, setParam } = useUrlState();
  const read = (k: string) => params.get(k) ?? "";
  const sortOrder = params.get("order");
  const chartView = params.get("view");

  const view = {
    sort: params.get("sort") || null,
    order: sortOrder === "asc" || sortOrder === "desc" ? (sortOrder as Order) : undefined,
    status: read("status"),
    query: read("q"),
    search: read("search"),
    branch: read("branch"),
    tab: boardTab(params),
    chart: isChartView(chartView) ? chartView : "trend",
    creating: params.get("new") === "1",
    archived: params.get("archived") === "1",
    /** `group=`/`agg=` when the board knows them; null = the default. */
    groupParam: parseGroup(params.get("group")),
    aggParam: parseAggregate(params.get("agg")),
  };

  const hidden = useParamSet(params, "hide");
  const shown = useParamSet(params, "show");
  const selected = useParamSet(params, "sel");
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

  const setters = useMemo(() => ({
    setStatus: (csv: string) => setParam("status", csv),
    setQuery: (q: string) => setParam("q", q),
    setSearch: (s: string) => setParam("search", s),
    setBranch: (b: string) => setParam("branch", b),
    setTab: (tab: BoardTab) => update((p) => setBoardTab(p, tab)),
    // Only the Charts tab picks a chart, so the pick keeps that tab open.
    setChart: (c: ChartView) =>
      update((p) => {
        if (c === "trend") p.delete("view");
        else p.set("view", c);
        setBoardTab(p, "charts");
      }),
    openCreate: (open: boolean) => setParam("new", open ? "1" : ""),
    toggleHidden: (col: string) => toggleIn("hide", col),
    /** Record the user's explicit choice for a column whose default depends
     *  on the rows: `show=` when on, `hide=` when off. */
    setColumnShown: (col: string, on: boolean) =>
      update((p) => {
        const drop = (name: string) => setAllParams(p, name, p.getAll(name).filter((v) => v !== col));
        drop("show");
        drop("hide");
        p.append(on ? "show" : "hide", col);
      }),
    /** Drop a column's `show=`/`hide=` entries, back to its default. */
    resetColumn: (col: string) =>
      update((p) => {
        for (const name of ["show", "hide"]) setAllParams(p, name, p.getAll(name).filter((v) => v !== col));
      }),
    toggleSelected: (verstr: string) => toggleIn("sel", verstr),
    /** Group the board by *group*; `group=` is left out at the default
     *  *dflt*, and the closed groups of the old grouping are forgotten. */
    setGroup: (group: GroupBy, dflt: GroupBy) =>
      update((p) => {
        if (group === dflt) p.delete("group");
        else p.set("group", group);
        p.delete("collapse");
      }),
    /** The aggregate a group header shows; `agg=` is left out at the default (when known). */
    setAggregate: (agg: Aggregate, dflt: Aggregate | undefined) => setParam("agg", agg === dflt ? "" : agg),
    /** Close or reopen a group (all start open, so `collapse=` lists the shut ones). */
    toggleCollapsed: (key: string) => toggleIn("collapse", key),
    setSelected: (verstrs: readonly string[]) => setAll("sel", verstrs),
    setArchived: (on: boolean) => setParam("archived", on ? "1" : ""),
    setOrder: (keys: readonly string[]) => setAll("col", keys),
    /** *pinned*: the pins in effect (the board's defaults without `pin=`). */
    moveColumn: (key: string, delta: number, defaultKeys: readonly string[], pinned?: readonly string[]) =>
      update((p) => {
        setAllParams(p, "col", moveKey(p.getAll("col"), key, delta, defaultKeys, pinned ?? p.getAll("pin")));
      }),
    /** Flip *key* in the pins in effect (*pinned*, else `pin=`). Landing on
     *  the board's *defaults* drops `pin=`; unpinning the last one otherwise
     *  writes `pin=-`, so the defaults don't come back. */
    togglePin: (key: string, pinned?: readonly string[], defaults: readonly string[] = []) =>
      update((p) => {
        const next = togglePinUtil(pinned ?? p.getAll("pin").filter((k) => k !== NO_PINS), key);
        const isDefault = next.length === defaults.length && next.every((k) => defaults.includes(k));
        setAllParams(p, "pin", isDefault ? [] : next.length ? next : [NO_PINS]);
      }),
  }), [setParam, toggleIn, setAll, update]);

  return {
    ...view,
    hidden, shown, selected, collapsed,
    colOrder, pinned,
    clickSort, ...setters,
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
