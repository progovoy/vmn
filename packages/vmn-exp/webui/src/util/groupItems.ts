/** The grouped board's table items (plan 22 G4): each group's header row,
 *  its loaded rows while open, and a `+N more` row for the rest. A loose
 *  group (a link grouping's runs with no link, F12) has no header: its rows
 *  and `+N more` row follow the groups as no one's members. */
import type { GroupAggregate, RunGroup } from "../apiGroups";
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

/** The table's items for grouped *data*, minus the *collapsed*
 *  groups' rows; with *keep* (a chart brush), only its rows and the groups
 *  that keep one. */
export function groupItems(
  data: GroupedRows, collapsed: ReadonlySet<string>,
  more: ReadonlyMap<string, MoreState> = new Map(), keep?: (r: ExperimentRow) => boolean,
): BoardItem[] {
  const byVerstr = new Map(data.rows.map((r) => [r.verstr, r]));
  const out: BoardItem[] = [];
  for (const group of data.groups) {
    const rows = group.verstrs.flatMap((v) => byVerstr.get(v) ?? []);
    const shown = keep ? rows.filter(keep) : rows;
    if (keep && !shown.length) continue;
    const open = group.loose || !collapsed.has(group.key);
    if (!group.loose) out.push({ item: "group", group, open, rows: shown.map((r) => r.verstr) });
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

/** The header each item is a member of: an open group's rows (as many as
 *  its header names) and its `+N more` row; null for a header and for the
 *  rows of no group (loose rows, an ungrouped board). */
export function memberOf(items: readonly BoardItem[]): (GroupHeaderItem | null)[] {
  let head: GroupHeaderItem | null = null;
  let left = 0;
  return items.map((it) => {
    if (isGroupItem(it) && it.item === "group") {
      head = it.open ? it : null;
      left = head ? it.rows.length : 0;
      return null;
    }
    if (isGroupItem(it)) return head && it.key === head.group.key ? head : null;
    if (left <= 0) return null;
    left -= 1;
    return head;
  });
}

/** Where each member sits under its header (plan 22 F11), by index: the
 *  group's last one `last`, the others `mid`. */
export function memberPlaces(items: readonly BoardItem[]): Map<number, MemberPlace> {
  const owner = memberOf(items);
  const out = new Map<number, MemberPlace>();
  owner.forEach((head, i) => {
    if (head) out.set(i, owner[i + 1] === head ? "mid" : "last");
  });
  return out;
}
