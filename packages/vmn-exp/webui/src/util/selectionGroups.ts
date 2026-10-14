/** Query groups of the app-wide selection: "Select all N matching" on a
 *  job's Runs tab selects the query itself (scope, q, status), which the
 *  server resolves, next to the explicit picks (runSelection.ts). A group
 *  keeps the board rows it was made over (`members`, in board order): they
 *  show ticked, Compare takes the first ten, and they are never also
 *  explicit picks. */
import { fmtCount } from "../util";
import { SELECT_ALL_CAP, notifySelection, readPicks, summarizePicks, writePicks, type RunPick } from "./runSelection";

/** Top runs of each group that Compare takes. */
export const COMPARE_PER_GROUP = 10;

export interface QueryGroup {
  /** The job's verstr. */
  scope: string;
  q: string;
  status: string;
  /** How many runs the query matched when it was selected. */
  count: number;
  job: string;
  /** The job's name, else its verstr. */
  label: string;
  members: RunPick[];
}

const KEY_PREFIX = "vmn-exp:selection-groups:";
const keyOf = (ws: string, app: string) => `${KEY_PREFIX}${ws}/${app}`;
type Query = Pick<QueryGroup, "scope" | "q" | "status">;
export const sameQuery = (a: Query, b: Query) => a.scope === b.scope && a.q === b.q && a.status === b.status;

/** The stored text, for change detection. */
export const rawGroups = (ws: string, app: string): string => sessionStorage.getItem(keyOf(ws, app)) ?? "[]";

export function parseGroups(raw: string): QueryGroup[] {
  try {
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed)
      ? parsed.filter((g): g is QueryGroup => typeof g?.scope === "string" && Array.isArray(g.members))
      : [];
  } catch {
    return [];
  }
}

export const readGroups = (ws: string, app: string): QueryGroup[] => parseGroups(rawGroups(ws, app));

export function writeGroups(ws: string, app: string, groups: readonly QueryGroup[], notify = true) {
  if (groups.length) sessionStorage.setItem(keyOf(ws, app), JSON.stringify(groups));
  else sessionStorage.removeItem(keyOf(ws, app));
  if (notify) notifySelection();
}

/** Add *group*, replacing the one of the same scope and query; the explicit
 *  picks it covers move into it. */
export function addQueryGroup(ws: string, app: string, group: QueryGroup) {
  const kept = { ...group, members: group.members.slice(0, SELECT_ALL_CAP) };
  const absorbed = new Set(kept.members.map((p) => p.verstr));
  writePicks(ws, app, readPicks(ws, app).filter((p) => !absorbed.has(p.verstr)), false);
  writeGroups(ws, app, [...readGroups(ws, app).filter((g) => !sameQuery(g, kept)), kept]);
}

export const removeQueryGroup = (ws: string, app: string, query: Query) =>
  writeGroups(ws, app, readGroups(ws, app).filter((g) => !sameQuery(g, query)));

/** Every verstr that shows selected: the explicit picks, then each group's members. */
export const selectedVerstrs = (picks: readonly RunPick[], groups: readonly QueryGroup[]) =>
  [...picks, ...groups.flatMap((g) => g.members)].map((p) => p.verstr);

/** Select exactly *verstrs*: a group whose members all stay is kept (its
 *  members are not picks); one that lost a member turns into explicit
 *  picks of the members that stay. */
export function selectExactly(ws: string, app: string, verstrs: readonly string[], metaOf?: (v: string) => RunPick | undefined) {
  const wanted = new Set(verstrs);
  const groups = readGroups(ws, app);
  const kept = groups.filter((g) => g.members.every((p) => wanted.has(p.verstr)));
  const inKept = new Set(kept.flatMap((g) => g.members.map((p) => p.verstr)));
  const known = new Map([...readPicks(ws, app), ...groups.flatMap((g) => g.members)].map((p) => [p.verstr, p]));
  const picks = verstrs.filter((v) => !inKept.has(v)).map((v) => metaOf?.(v) ?? known.get(v) ?? { verstr: v });
  writePicks(ws, app, picks, false);
  writeGroups(ws, app, kept);
}

/** `4,012 runs from 3 jobs`: the explicit picks plus every group's count. */
export const summarizeSelection = (picks: readonly RunPick[], groups: readonly QueryGroup[]) =>
  summarizePicks(picks, groups);

/** `all 4,000 matching in hist-0012 (status = failed)`. */
export function describeGroup(g: QueryGroup) {
  const query = [g.q, g.status ? `status = ${g.status}` : ""].filter(Boolean).join(" and ");
  return `all ${fmtCount(g.count)} matching in ${g.label}${query ? ` (${query})` : ""}`;
}

/** The runs Compare takes: the explicit picks, then up to the top
 *  COMPARE_PER_GROUP runs of each group in the board's order. */
export const compareList = (picks: readonly RunPick[], groups: readonly QueryGroup[]) =>
  [...picks.map((p) => p.verstr), ...groups.flatMap((g) => g.members.slice(0, COMPARE_PER_GROUP).map((p) => p.verstr))];

/** A group as a bulk action's body (`actions/exp_*` by query). */
export function queryBody(g: Query) {
  return { scope: g.scope, ...(g.q ? { q: g.q } : {}), ...(g.status ? { status: g.status } : {}) };
}
