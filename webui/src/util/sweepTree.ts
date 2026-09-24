/** Collapsible sweeps: which loaded rows an open/shut outer run hides. */
import type { ExperimentRow } from "../types";

/** An outer run with more inner runs than this starts collapsed. */
export const AUTO_COLLAPSE_CHILDREN = 20;

export const collapsedByDefault = (r: ExperimentRow) =>
  (r.children?.length ?? 0) > AUTO_COLLAPSE_CHILDREN;

export function isCollapsed(
  r: ExperimentRow, expanded: ReadonlySet<string>, collapsed: ReadonlySet<string>,
): boolean {
  if (!r.children?.length) return false;
  if (collapsed.has(r.verstr)) return true;
  return collapsedByDefault(r) && !expanded.has(r.verstr);
}

/** *rows* minus every run with a collapsed ancestor among the loaded rows. */
export function visibleRows(
  rows: ExperimentRow[], expanded: ReadonlySet<string>, collapsed: ReadonlySet<string>,
): ExperimentRow[] {
  const byVerstr = new Map(rows.map((r) => [r.verstr, r]));
  const shut = new Set(rows.filter((r) => isCollapsed(r, expanded, collapsed)).map((r) => r.verstr));
  if (shut.size === 0) return rows;
  const hidden = (r: ExperimentRow): boolean => {
    const seen = new Set<string>();
    for (let p = r.parent; p && !seen.has(p); p = byVerstr.get(p)?.parent) {
      if (shut.has(p)) return true;
      seen.add(p);
    }
    return false;
  };
  return rows.filter((r) => !hidden(r));
}
