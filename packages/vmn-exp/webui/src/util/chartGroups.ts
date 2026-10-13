/** The Charts tab's colours on a grouped board (plan 22 G7): every charted
 *  run in its group's colour, the groups in the board's order, plus the
 *  legend that names them. */
import { groupKeyText, NONE_GROUP } from "../apiGroups";
import type { ExperimentColumns, ExperimentRow } from "../types";
import { runColor } from "../util";
import type { BoardGroup } from "./groupItems";

/** The columns key carrying a run's group key on the board grouped by *field*. */
export const groupColumn = (field: string) => `group:${field}`;
/** The runs with no value (`(none)`, `(no parent run)`). */
export const NO_GROUP_COLOR = "var(--text-3)";

const TARGET_LINKS = new Set(["parent", "forked_from", "rerun_of", "code_verstr"]);

export interface ChartGroup {
  key: string;
  label: string;
  color: string;
  /** The charted runs in it. */
  count: number;
}

export interface ChartGroups {
  /** verstr -> colour; a run of no known group has none. */
  colorOf: ReadonlyMap<string, string>;
  /** The groups with a charted run, in colour order, the no-value group last. */
  legend: ChartGroup[];
}

/** A group's name as its header shows it; for a group the board has not
 *  loaded, its label as the server would give it. */
function labelOf(key: string, field: string, loaded: BoardGroup | undefined): string {
  if (loaded) return loaded.target?.name || loaded.label;
  if (key === NONE_GROUP) return field === "parent" ? "(no parent run)" : "(none)";
  const text = groupKeyText(key);
  return TARGET_LINKS.has(field) ? text : `${field} = ${text}`;
}

/** Each charted run's group colour, with *keyOf* (verstr -> group key) and
 *  the board's loaded *groups* (their order and names). */
export function chartGroups(
  rows: readonly ExperimentRow[], keyOf: ReadonlyMap<string, string>,
  groups: readonly BoardGroup[], field: string,
): ChartGroups {
  const count = new Map<string, number>();
  for (const r of rows) {
    const key = keyOf.get(r.verstr);
    if (key !== undefined) count.set(key, (count.get(key) ?? 0) + 1);
  }
  const loaded = new Map(groups.map((g) => [g.key, g]));
  const order = [...groups.map((g) => g.key), ...count.keys()]
    .filter((k, i, all) => count.has(k) && k !== NONE_GROUP && all.indexOf(k) === i);
  if (count.has(NONE_GROUP)) order.push(NONE_GROUP);
  const legend = order.map((key, i) => ({
    key, label: labelOf(key, field, loaded.get(key)), count: count.get(key)!,
    color: key === NONE_GROUP ? NO_GROUP_COLOR : runColor(i),
  }));
  const colorByKey = new Map(legend.map((e) => [e.key, e.color]));
  const colorOf = new Map<string, string>();
  for (const r of rows) {
    const key = keyOf.get(r.verstr);
    if (key !== undefined) colorOf.set(r.verstr, colorByKey.get(key)!);
  }
  return { colorOf, legend };
}

/** verstr -> group key from the columns' `group:<field>`; null without it. */
export function chartGroupKeys(data: ExperimentColumns, field: string): Map<string, string> | null {
  const values = data.columns[groupColumn(field)];
  if (!values) return null;
  return new Map(data.verstrs.map((v, i) => [v, String(values[i] ?? NONE_GROUP)]));
}

/** verstr -> group key over the board's loaded groups. */
export const loadedGroupKeys = (groups: readonly BoardGroup[]): Map<string, string> =>
  new Map(groups.flatMap((g) => g.verstrs.map((v) => [v, g.key] as const)));
