/** The grouped board's table items (plan 22 G4): each group's header row,
 *  its loaded rows while open, and a `+N more` row for the rest. */
import { NONE_GROUP, type GroupAggregate, type RunGroup } from "../apiGroups";
import type { ExperimentRow } from "../types";

/** A group as the board caches it: its rows by verstr, so an edit to the
 *  app's cached rows (a note, tags) reaches it. */
export type BoardGroup = Omit<RunGroup, "rows"> & { verstrs: string[] };

/** The grouped payload as cached: `rows`/`total` like any list of the app's
 *  rows, plus the groups over them. */
export interface GroupedRows {
  rows: ExperimentRow[];
  total: number;
  groups: BoardGroup[];
  total_groups: number;
  /** The payload's top level: the effective aggregate, the running rows. */
  aggregate?: GroupAggregate;
  running?: number;
}

export type MoreState = "idle" | "loading" | "error";

export interface GroupHeaderItem {
  item: "group";
  group: BoardGroup;
  open: boolean;
  /** False for the parent grouping's `(no parent run)`: always open. */
  foldable: boolean;
  /** Its loaded rows (the ones *keep* passes), shown or folded: what its
   *  checkbox selects (plan 22 G7). */
  rows: string[];
}

export interface GroupMoreItem {
  item: "more";
  key: string;
  remaining: number;
  state: MoreState;
}

export type BoardItem = ExperimentRow | GroupHeaderItem | GroupMoreItem;

export const isGroupItem = (it: BoardItem): it is GroupHeaderItem | GroupMoreItem => "item" in it;

/** The table's items for *data* grouped by *field*, minus the *collapsed*
 *  groups' rows; with *keep* (a chart brush), only its rows and the groups
 *  that keep one. */
export function groupItems(
  data: GroupedRows, field: string, collapsed: ReadonlySet<string>,
  more: ReadonlyMap<string, MoreState> = new Map(), keep?: (r: ExperimentRow) => boolean,
): BoardItem[] {
  const byVerstr = new Map(data.rows.map((r) => [r.verstr, r]));
  const out: BoardItem[] = [];
  for (const group of data.groups) {
    const rows = group.verstrs.flatMap((v) => byVerstr.get(v) ?? []);
    const shown = keep ? rows.filter(keep) : rows;
    if (keep && !shown.length) continue;
    const foldable = !(field === "parent" && group.key === NONE_GROUP);
    const open = !foldable || !collapsed.has(group.key);
    out.push({ item: "group", group, open, foldable, rows: shown.map((r) => r.verstr) });
    if (!open) continue;
    out.push(...shown);
    const remaining = group.rows_total - group.verstrs.length;
    if (remaining > 0 && !keep) {
      out.push({ item: "more", key: group.key, remaining, state: more.get(group.key) ?? "idle" });
    }
  }
  return out;
}

/** The runs among *items*. */
export const boardRows = (items: readonly BoardItem[]): ExperimentRow[] =>
  items.filter((it): it is ExperimentRow => !isGroupItem(it));

export type MemberPlace = "mid" | "last";

/** Where each item of a foldable group sits under its header (plan 22 F11):
 *  its rows and `+N more` row by index, the one before the next header (or
 *  the end) `last`. The inline `(no parent run)` group's rows are no one's
 *  members. */
export function memberPlaces(items: readonly BoardItem[]): Map<number, MemberPlace> {
  const out = new Map<number, MemberPlace>();
  let inGroup = false;
  items.forEach((it, i) => {
    if (isGroupItem(it) && it.item === "group") {
      inGroup = it.foldable;
      return;
    }
    if (!inGroup) return;
    const next = items[i + 1];
    out.set(i, !next || (isGroupItem(next) && next.item === "group") ? "last" : "mid");
  });
  return out;
}
