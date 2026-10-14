import { useCallback, useEffect, useRef } from "react";
import { api } from "../api";
import type { RowsFilter } from "../queries";
import type { ExperimentRow } from "../types";
import { SELECT_ALL_CAP, pickOf, type RunPick } from "../util/runSelection";
import { addQueryGroup, sameQuery } from "../util/selectionGroups";
import { useRunSelection, type PickMeta } from "./useRunSelection";

/** How many of the rows on screen are selected, for the header checkbox. */
export type HeaderCheck = "none" | "some" | "all";

/** A selection by query (plan 23 S4): a job's subtree under the board's
 *  filters, resolved by the server. */
export interface QuerySelection {
  scope: string;
  q: string;
  status: string;
  /** The job's name, for the tray. */
  label?: string;
}

interface Selection {
  selected: ReadonlySet<string>;
  toggleSelected: (verstr: string, meta?: RunPick) => void;
  setSelected: (verstrs: readonly string[], metaOf?: PickMeta) => void;
}

/** The leaderboard's selection actions: toggle (shift extends a range over
 *  the rows on screen), the header checkbox over those rows, a group
 *  header's over its rows, and select every filtered run (archive is the
 *  tray's, SelectionTray).
 *
 *  With *byQuery* (a job's Runs tab) "select all" adds the query itself to
 *  the app's selection, without a cap, next to the other picks: `matching`
 *  is its count while it stays selected. Unticking one of its runs turns it
 *  back into explicit picks of the others (selectExactly). */
export function useBoardSelection(
  ws: string, app: string, filter: RowsFilter, rows: readonly ExperimentRow[],
  sel: Selection, byQuery?: QuerySelection,
) {
  const anchor = useRef<string | null>(null);
  // Read at click time, so `toggle` keeps one identity and memoized rows
  // are not re-rendered by it.
  const latest = useRef({ rows, sel });
  latest.current = { rows, sel };
  // Picks carry what their rows say (their job, name, @N) for the tray.
  const metaOf = useCallback((verstr: string) => {
    const r = latest.current.rows.find((row) => row.verstr === verstr);
    return r && pickOf(r);
  }, []);
  const setPicks = useCallback((verstrs: readonly string[]) => {
    const byVerstr = new Map(latest.current.rows.map((r) => [r.verstr, r]));
    latest.current.sel.setSelected(verstrs, (v) => {
      const r = byVerstr.get(v);
      return r && pickOf(r);
    });
  }, []);

  const toggle = useCallback((verstr: string, range: boolean) => {
    const { rows, sel } = latest.current;
    const from = anchor.current ? rows.findIndex((r) => r.verstr === anchor.current) : -1;
    const to = rows.findIndex((r) => r.verstr === verstr);
    anchor.current = verstr;
    if (!range || from < 0 || to < 0) {
      sel.toggleSelected(verstr, metaOf(verstr));
      return;
    }
    const [lo, hi] = from < to ? [from, to] : [to, from];
    const span = rows.slice(lo, hi + 1).map((r) => r.verstr);
    setPicks([...new Set([...sel.selected, ...span])]);
  }, [metaOf, setPicks]);
  /** The next shift-toggle starts a range of its own. */
  const clearAnchor = useCallback(() => { anchor.current = null; }, []);

  /** How many of *verstrs* are selected. */
  const checkOf = (verstrs: readonly string[]): HeaderCheck => {
    const n = verstrs.filter((v) => sel.selected.has(v)).length;
    return n === 0 ? "none" : n === verstrs.length ? "all" : "some";
  };
  /** Select every one of *verstrs* or, once they all are, clear them (runs
   *  selected elsewhere, e.g. by "select all matching", stay selected). */
  const toggleRows = (verstrs: readonly string[]) => {
    if (checkOf(verstrs) !== "all") {
      setPicks([...new Set([...sel.selected, ...verstrs])]);
      return;
    }
    const drop = new Set(verstrs);
    setPicks([...sel.selected].filter((v) => !drop.has(v)));
  };
  const shown = rows.map((r) => r.verstr);
  const headerCheck = checkOf(shown);
  const toggleAll = () => toggleRows(shown);

  // The board's query, selected as a group: its rows show ticked, and rows
  // loaded since (more pages, live arrivals) join its members.
  const { groups } = useRunSelection(ws, app);
  const active = byQuery ? groups.find((g) => sameQuery(g, byQuery)) : undefined;
  useEffect(() => {
    if (!active || active.members.length >= SELECT_ALL_CAP) return;
    const known = new Set(active.members.map((p) => p.verstr));
    const missing = rows.filter((r) => !known.has(r.verstr));
    if (missing.length) addQueryGroup(ws, app, { ...active, members: [...active.members, ...missing.map(pickOf)] });
  }, [ws, app, active, rows]);

  /** Every run the filter matches (up to the cap); the loaded rows on a
   *  server without the columns endpoint. By query: adds the query (its
   *  *total* runs) to the selection, absorbing its loaded rows. */
  const selectAll = async (total = 0) => {
    if (byQuery) {
      const { scope, q, status, label } = byQuery;
      addQueryGroup(ws, app, {
        scope, q, status, count: total, job: scope, label: label || scope, members: rows.map(pickOf),
      });
      return;
    }
    try {
      const cols = await api.experimentsColumns(ws, app, [], { ...filter, limit: SELECT_ALL_CAP });
      setPicks(cols.verstrs);
    } catch {
      setPicks(rows.map((r) => r.verstr)); // the store caps it
    }
  };

  return {
    toggle, clearAnchor, headerCheck, toggleAll, checkOf, toggleRows, selectAll,
    matching: active?.count ?? null, uncapped: Boolean(byQuery),
  };
}
