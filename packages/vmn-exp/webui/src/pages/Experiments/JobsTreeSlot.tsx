/** An Outer runs row's tree, opened in place (plan 28 N6): the rows whose
 *  expander is on get a slot right below them holding their JobTree. */
import { useCallback, useMemo, useState } from "react";
import type { ExperimentRow } from "../../types";
import { isGroupItem, type BoardItem } from "../../util/groupItems";
import JobTree, { EMBEDDED_HEIGHT } from "../Job/JobTree";
import type { JobContext } from "./JobCells";
import { JOB_COLUMNS } from "./jobColumns";

export interface TreeSlot {
  item: "tree";
  row: ExperimentRow;
}

type GridItem = BoardItem | TreeSlot;

export const SLOT_HEIGHT = EMBEDDED_HEIGHT + 16;

export const isTreeSlot = (it: GridItem | undefined): it is TreeSlot => it != null && "item" in it && it.item === "tree";

/** *items* with a tree slot after each row whose tree is open, and the toggle. */
export function useTreeSlots(items: readonly BoardItem[]) {
  const [open, setOpen] = useState<ReadonlySet<string>>(new Set());
  const toggle = useCallback((verstr: string) => setOpen((s) => {
    const next = new Set(s);
    if (!next.delete(verstr)) next.add(verstr);
    return next;
  }), []);
  const list = useMemo(() => items.flatMap((it): GridItem[] =>
    !isGroupItem(it) && open.has(it.verstr) ? [it, { item: "tree", row: it }] : [it]), [items, open]);
  return { list, open, toggle };
}

export function JobsTreeSlot({ slot, ws, app, ctx }: { slot: TreeSlot; ws: string; app: string; ctx: JobContext }) {
  return (
    <tr className="jobs-tree-slot" style={{ height: SLOT_HEIGHT }}>
      <td colSpan={JOB_COLUMNS.length}>
        <JobTree ws={ws} app={app} verstr={slot.row.verstr} name={slot.row.name || undefined}
          attention={ctx.attention} embedded />
      </td>
    </tr>
  );
}
