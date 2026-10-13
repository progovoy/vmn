import { useMemo, useState } from "react";
import type { ExperimentRow } from "../types";

/** The charted runs that follow the board's selection (plan 22 F7): with rows
 *  selected only those, until "Show all" — which keeps the selection and
 *  lasts until the selection changes. */
export function useChartSelection(rows: ExperimentRow[], selected: ReadonlySet<string>) {
  const [allFor, setAllFor] = useState<ReadonlySet<string> | null>(null);
  const picked = useMemo(
    () => (selected.size ? rows.filter((r) => selected.has(r.verstr)) : null),
    [rows, selected],
  );
  const showingAll = allFor === selected;
  return {
    rows: picked && !showingAll ? picked : rows,
    /** How many selected runs the chart has; null without a selection. */
    selectedCount: picked ? picked.length : null,
    showingAll,
    setShowAll: (all: boolean) => setAllFor(all ? selected : null),
  };
}
