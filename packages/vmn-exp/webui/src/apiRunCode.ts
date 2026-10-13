/** A run's code for the run page (plan 20 K2, K3): its patch text with the
 *  files it changes, and the runs the Changes card can diff it against. */
import { appTag, get } from "./http";

/** One file of a patch, its lines counted from the hunks of the served text. */
export interface PatchFile {
  path: string;
  added: number;
  removed: number;
}

/** `vmn-exp show --patch --json`'s `patch`, plus `files`. Without text,
 *  `reason` says why: `no_code` (clean tree), `code_missing` (its code object
 *  is gone) or `untracked_only` (with the paths, unless the tarball is unreadable). */
export interface RunPatch {
  text: string | null;
  truncated?: boolean;
  reason?: "no_code" | "code_missing" | "untracked_only";
  untracked_files?: string[];
  files: PatchFile[];
}

/** A run named by `@N name` and its status. */
export interface BaselineRun {
  verstr: string;
  idx: number | null;
  name: string | null;
  status: string;
}

/** Each key only when it exists: `base` is the run itself when it captured a
 *  patch; `previous` the latest earlier run of its branch and command; `best`
 *  the best other run on the primary declared goal. */
export interface RunBaselines {
  base?: BaselineRun;
  parent?: BaselineRun;
  forked_from?: BaselineRun;
  rerun_of?: BaselineRun;
  previous?: BaselineRun;
  best?: BaselineRun;
}

const runBase = (ws: string, app: string, verstr: string) =>
  `/workspaces/${ws}/apps/${appTag(app)}/experiments/${encodeURIComponent(verstr)}`;

/** The run's own patches (working tree, local commits, deps), at most
 *  *maxBytes* of text (server default 200000). */
export function fetchRunPatch(ws: string, app: string, verstr: string, maxBytes?: number): Promise<RunPatch> {
  const qs = maxBytes == null ? "" : `?${new URLSearchParams({ max_bytes: String(maxBytes) })}`;
  return get<RunPatch>(`${runBase(ws, app, verstr)}/patch${qs}`);
}

export function fetchRunBaselines(ws: string, app: string, verstr: string): Promise<RunBaselines> {
  return get<RunBaselines>(`${runBase(ws, app, verstr)}/baselines`);
}
