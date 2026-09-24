import { useRef, useState } from "react";
import { api } from "../api";
import type { RowsFilter } from "../queries";
import type { ExperimentRow } from "../types";
import { useJob } from "../components/ui";

/** Most runs "select all" picks — and one archive job takes. */
export const SELECT_ALL_CAP = 500;

export type ArchiveVerb = "archive" | "unarchive";

interface Selection {
  selected: ReadonlySet<string>;
  toggleSelected: (verstr: string) => void;
  setSelected: (verstrs: readonly string[]) => void;
}

/** The leaderboard's selection actions: toggle (shift extends a range over
 *  the rows on screen), select every filtered run, and bulk archive. */
export function useBoardSelection(
  ws: string, app: string, filter: RowsFilter, rows: readonly ExperimentRow[],
  sel: Selection, onArchived: () => void,
) {
  const anchor = useRef<string | null>(null);
  const [archiveError, setArchiveError] = useState<string | null>(null);

  const toggle = (verstr: string, range: boolean) => {
    const from = anchor.current ? rows.findIndex((r) => r.verstr === anchor.current) : -1;
    const to = rows.findIndex((r) => r.verstr === verstr);
    anchor.current = verstr;
    if (!range || from < 0 || to < 0) {
      sel.toggleSelected(verstr);
      return;
    }
    const [lo, hi] = from < to ? [from, to] : [to, from];
    const span = rows.slice(lo, hi + 1).map((r) => r.verstr);
    sel.setSelected([...new Set([...sel.selected, ...span])]);
  };

  /** Every run the filter matches (up to the cap); the loaded rows on a
   *  server without the columns endpoint. */
  const selectAll = async () => {
    try {
      const cols = await api.experimentsColumns(ws, app, [], { ...filter, limit: SELECT_ALL_CAP });
      sel.setSelected(cols.verstrs.slice(0, SELECT_ALL_CAP));
    } catch {
      sel.setSelected(rows.slice(0, SELECT_ALL_CAP).map((r) => r.verstr));
    }
  };

  const job = useJob((j) => {
    if (j.status === "succeeded") {
      sel.setSelected([]);
      onArchived();
    } else {
      setArchiveError(`${j.command.join(" ") || "archive"} failed`);
    }
  });
  const archive = (verb: ArchiveVerb) => {
    setArchiveError(null);
    job.run(ws, app, `exp_${verb}`, { verstrs: [...sel.selected].slice(0, SELECT_ALL_CAP) });
  };

  return {
    toggle, selectAll, archive,
    archiving: job.job?.status === "running",
    archiveError: archiveError ?? job.error,
  };
}
