/** The tree's pages (plan 28 N6): `experiments?children_of=<v>`, a run's
 *  direct children in the board's order, each with children carrying its
 *  job summary, every one an `open` hint. Kept apart from api.ts so tests
 *  mocking `../api` keep the tree's own. */
import { appTag, get } from "./http";
import type { ExperimentRow, JobRollup } from "./types";

/** A child job's summary: attention over its own subtree (plan 28 P1) and,
 *  with the app's `split_by`, its runs per value (P3). */
export interface TreeJob extends JobRollup {
  attention_rank?: number;
  split?: string;
  by?: { key: string | null; label: string; total: number }[];
}

export interface TreeRow extends ExperimentRow {
  job?: TreeJob | null;
  /** Whether the tree unfolds it: attention or live runs below. */
  open?: boolean;
  /** A run without children: the attention queries it matches itself. */
  attention?: Record<string, number>;
  /** Under a filter: the runs of its subtree (itself included) passing it. */
  matched?: number;
}

export interface TreePage {
  rows: TreeRow[];
  total: number;
  next_cursor?: string | null;
  /** The app's `experiment.ui.tree_columns`: show keys per `tags.kind` value. */
  tree_columns?: Record<string, string[]>;
}

/** The Runs tab's filters a tree is asked under: its status and query
 *  keep the children whose subtree holds a passing run (`match_subtree`). */
export interface TreeFilter {
  status?: string;
  query?: string;
  sort?: string;
  order?: "asc" | "desc";
  archived?: boolean;
}

const TREE_PAGE = 100;

function setTreeFilter(p: URLSearchParams, f: TreeFilter) {
  if (f.status) p.set("status", f.status);
  if (f.query) p.set("q", f.query);
  if (f.sort) p.set("sort", f.sort);
  if (f.order) p.set("order", f.order);
  if (f.archived) p.set("archived", "1");
  if (f.status || f.query) p.set("match_subtree", "1");
}

export function fetchChildren(
  ws: string, app: string, parent: string, opts: { offset?: number; filter?: TreeFilter } = {},
): Promise<TreePage> {
  const p = new URLSearchParams({ children_of: parent, offset: String(opts.offset ?? 0), limit: String(TREE_PAGE) });
  setTreeFilter(p, opts.filter ?? {});
  return get<TreePage>(`/workspaces/${ws}/apps/${appTag(app)}/experiments?${p}`);
}
