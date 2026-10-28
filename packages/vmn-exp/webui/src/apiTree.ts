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
}

export interface TreePage {
  rows: TreeRow[];
  total: number;
  next_cursor?: string | null;
  /** The app's `experiment.ui.tree_columns`: show keys per `tags.kind` value. */
  tree_columns?: Record<string, string[]>;
}

const TREE_PAGE = 100;

export function fetchChildren(ws: string, app: string, parent: string, opts: { offset?: number } = {}): Promise<TreePage> {
  const p = new URLSearchParams({ children_of: parent, offset: String(opts.offset ?? 0), limit: String(TREE_PAGE) });
  return get<TreePage>(`/workspaces/${ws}/apps/${appTag(app)}/experiments?${p}`);
}
