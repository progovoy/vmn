/** The tree's rows (plan 28 N6), pure: the visible items walked from the
 *  loaded children pages, a node's worst attention, and the text of the
 *  columns the app's `tree_columns` name for a node's kind. */
import type { TreeRow } from "../apiTree";
import type { AttentionEntry } from "../shell/contracts";
import { fmtDuration, fmtParam, fmtVal } from "../util";

/** What is loaded of each parent's children: pages asked for, and each one's rows. */
export interface TreePages {
  count: (parent: string) => number;
  page: (parent: string, i: number) => { rows: TreeRow[]; total: number } | undefined;
}

export interface TreeNodeItem {
  kind: "node";
  row: TreeRow;
  /** 0 for the outer run's children. */
  depth: number;
  parent: string;
  expandable: boolean;
  expanded: boolean;
  /** Its place among its siblings, 1-based, and how many there are. */
  posinset: number;
  setsize: number;
}

export type TreeItem =
  | TreeNodeItem
  | { kind: "more"; parent: string; depth: number; remaining: number }
  | { kind: "loading"; parent: string; depth: number };

/** Nesting deeper than this is drawn folded (a parent loop never recurses). */
const MAX_DEPTH = 32;

const expandable = (r: TreeRow) => Boolean(r.job) || (r.children?.length ?? 0) > 0;

/** An item's identity across renders: a node by its place, the others by their parent. */
export const itemKey = (it: TreeItem) =>
  (it.kind === "node" ? `n:${it.parent}:${it.row.verstr}` : `${it.kind}:${it.parent}`);

/** The items under *root*: a node unfolds when the reader opened it
 *  (*overrides*), else when the server hints `open`; *wanted* are the
 *  parents whose children are shown, the ones to fetch. */
export function treeItems(root: string, pages: TreePages, overrides: ReadonlyMap<string, boolean>) {
  const items: TreeItem[] = [];
  const wanted: string[] = [];
  const seen = new Set<string>([root]);

  const walk = (parent: string, depth: number) => {
    wanted.push(parent);
    const rows: TreeRow[] = [];
    let total = 0;
    let loading = false;
    for (let i = 0; i < pages.count(parent); i++) {
      const p = pages.page(parent, i);
      if (!p) { loading = true; break; }
      rows.push(...p.rows);
      total = p.total;
    }
    const setsize = Math.max(total, rows.length);
    rows.forEach((row, i) => {
      const canOpen = expandable(row) && depth + 1 < MAX_DEPTH && !seen.has(row.verstr);
      const expanded = canOpen && (overrides.get(row.verstr) ?? row.open ?? false);
      items.push({ kind: "node", row, depth, parent, expandable: canOpen, expanded, posinset: i + 1, setsize });
      if (expanded) {
        seen.add(row.verstr);
        walk(row.verstr, depth + 1);
      }
    });
    if (loading) items.push({ kind: "loading", parent, depth });
    else if (rows.length < total) items.push({ kind: "more", parent, depth, remaining: total - rows.length });
  };

  walk(root, 0);
  return { items, wanted };
}

type Part = AttentionEntry & { count: number };
const outranks = (a: Part, b: Part) => (a.level !== b.level ? a.level === "error" : a.count > b.count);

/** A node's worst attention part: error level first, then the most runs. */
export function worstAttention(r: TreeRow, entries: readonly AttentionEntry[]): Part | null {
  const counts = r.job?.attention ?? r.attention ?? {};
  let worst: Part | null = null;
  for (const e of entries) {
    const part = { ...e, count: counts[e.key] ?? 0 };
    if (part.count > 0 && (!worst || outranks(part, worst))) worst = part;
  }
  return worst;
}

const MISSING = "—";

/** `[label, text]` of a show key (`m:`/`p:`/`t:`/`c:<name>`) on *r*. */
export function cellText(r: TreeRow, key: string): [string, string] {
  const name = key.slice(2);
  const shown = (v: unknown, fmt: (v: never) => string) => (v == null ? MISSING : fmt(v as never));
  switch (key.slice(0, 2)) {
    case "m:": return [name, shown(r.metrics[name], fmtVal)];
    case "p:": return [name, shown(r.params?.[name], fmtParam)];
    case "t:": return [name, shown(r.tags?.[name], String)];
  }
  if (name === "ratio") return ["vs siblings", shown(r.duration_ratio, (v: number) => `${v.toFixed(1)}×`)];
  if (name === "duration" || name === "queue") {
    return [name, shown(name === "queue" ? r.queue_sec : r.duration_sec, fmtDuration)];
  }
  return [name, shown((r as unknown as Record<string, unknown>)[name], fmtParam)];
}

/** The show keys the app's *columns* name for *r*'s `tags.kind`. */
export const kindColumns = (r: TreeRow, columns: Record<string, string[]> | undefined) =>
  (r.tags?.kind && columns?.[r.tags.kind]) || [];
