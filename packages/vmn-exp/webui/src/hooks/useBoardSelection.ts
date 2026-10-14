import { useCallback, useRef, useState } from "react";
import { api } from "../api";
import type { RowsFilter } from "../queries";
import type { ExperimentRow } from "../types";
import { SELECT_ALL_CAP, pickOf, type RunPick } from "../util/runSelection";
import { useArchiveJob, type ArchiveVerb } from "./useArchiveJob";
import type { PickMeta } from "./useRunSelection";

export type { ArchiveVerb };
/** How many of the rows on screen are selected, for the header checkbox. */
export type HeaderCheck = "none" | "some" | "all";

/** A selection by query (plan 23 S4): a job's subtree under the board's
 *  filters, resolved by the server. */
export interface QuerySelection {
  scope: string;
  q: string;
  status: string;
}

interface Selection {
  selected: ReadonlySet<string>;
  toggleSelected: (verstr: string, meta?: RunPick) => void;
  setSelected: (verstrs: readonly string[], metaOf?: PickMeta) => void;
}

/** The leaderboard's selection actions: toggle (shift extends a range over
 *  the rows on screen), the header checkbox over those rows, a group
 *  header's over its rows, select every filtered run, and bulk archive.
 *
 *  With *byQuery* (a job's Runs tab) "select all" selects the query itself,
 *  without a cap: `matching` counts it until the selection or the filters
 *  change, and archive then sends the query, after a `dry_run` count. */
export function useBoardSelection(
  ws: string, app: string, filter: RowsFilter, rows: readonly ExperimentRow[],
  sel: Selection, onArchived: () => void, byQuery?: QuerySelection,
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

  // What a selection by query stands for: valid while neither it nor the
  // selection it was made over has changed.
  const [byQueryAll, setByQueryAll] = useState<{ count: number; key: string } | null>(null);
  const queryKey = `${JSON.stringify(byQuery ?? null)}|${[...sel.selected].join(",")}`;
  const matching = byQuery && byQueryAll?.key === queryKey ? byQueryAll.count : null;
  const queryBody = () => {
    const { scope, q, status } = byQuery!;
    return { scope, ...(q ? { q } : {}), ...(status ? { status } : {}) };
  };

  /** Every run the filter matches (up to the cap); the loaded rows on a
   *  server without the columns endpoint. By query: the query's *total*. */
  const selectAll = async (total = 0) => {
    if (byQuery) {
      const loaded = rows.slice(0, SELECT_ALL_CAP).map((r) => r.verstr);
      setPicks(loaded);
      setByQueryAll({ count: total, key: `${JSON.stringify(byQuery)}|${loaded.join(",")}` });
      return;
    }
    try {
      const cols = await api.experimentsColumns(ws, app, [], { ...filter, limit: SELECT_ALL_CAP });
      setPicks(cols.verstrs);
    } catch {
      setPicks(rows.map((r) => r.verstr)); // the store caps it
    }
  };

  const job = useArchiveJob(ws, app, () => {
    setPicks([]);
    onArchived();
  });
  // The store caps the selection, so it fits one archive job.
  const archive = (verb: ArchiveVerb) => job.run(verb, matching !== null ? queryBody() : { verstrs: [...sel.selected] });
  /** How many runs archiving the selection by query acts on (null: not by query). */
  const preview = matching === null ? undefined
    : (verb: ArchiveVerb) => api.actionPreview(ws, app, `exp_${verb}`, queryBody()).then((p) => p.count);

  return {
    toggle, clearAnchor, headerCheck, toggleAll, checkOf, toggleRows, selectAll, archive,
    matching, preview, uncapped: Boolean(byQuery),
    archiving: job.archiving,
    archiveError: job.archiveError,
  };
}
