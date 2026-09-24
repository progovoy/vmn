import type { ExperimentDetail, ExperimentRow, RunStatus } from "../types";

/** What the top of the Run page shows. A leaderboard row carries all of it,
 *  so the page can paint from the row cache before the detail arrives. */
export interface RunSummary {
  verstr: string;
  /** Human-readable name, when the run has one. */
  name: string | null;
  tags: Record<string, string>;
  branch: string | null;
  note: string | null;
  status: RunStatus | null;
  metrics: ExperimentDetail["metrics"];
  params: Record<string, unknown> | null;
}

/** One shared empty tag set, so an untagged run's tags keep their identity. */
const NO_TAGS: Record<string, string> = Object.freeze({}) as Record<string, string>;

/** The verbatim params, or snapshot `user_meta` for a record without any. */
const paramsOrMeta = (
  params: Record<string, unknown> | undefined, meta: Record<string, unknown> | null | undefined,
) => (params && Object.keys(params).length > 0 ? params : meta ?? null);

export function summaryFromDetail(d: ExperimentDetail): RunSummary {
  const meta = d.metadata;
  return {
    verstr: meta.verstr,
    name: (meta.name as string | undefined) || null,
    tags: (meta.tags as Record<string, string> | undefined) ?? NO_TAGS,
    branch: (meta.branch as string | undefined) ?? null,
    note: (meta.note as string | undefined) || null,
    status: d.status ?? null,
    metrics: d.metrics,
    params: paramsOrMeta(d.params, meta.user_meta as Record<string, unknown> | null | undefined),
  };
}

function statusFromRow(r: ExperimentRow): RunStatus | null {
  if (!r.status) return null;
  return {
    status: r.status,
    exit_code: r.exit_code ?? null,
    started_at: r.started_at ?? null,
    finished_at: r.finished_at ?? null,
    heartbeat: r.heartbeat ?? null,
    duration_sec: r.duration_sec ?? null,
    pid: r.pid ?? null,
    host: r.host ?? null,
    command: r.command ?? null,
    stale_sec: r.stale_sec ?? null,
    heartbeat_interval_sec: r.heartbeat_interval_sec ?? null,
    parent: r.parent ?? null,
    children: r.children ?? [],
    kind: r.kind ?? "single",
    depth: r.depth ?? 0,
    tree_status: r.tree_status ?? null,
    last_metric_at: r.last_metric_at ?? null,
  };
}

export function summaryFromRow(r: ExperimentRow): RunSummary {
  return {
    verstr: r.verstr,
    name: r.name || null,
    tags: r.tags ?? NO_TAGS,
    branch: r.branch,
    note: r.note,
    status: statusFromRow(r),
    metrics: r.metrics,
    params: paramsOrMeta(r.params, r.user_meta),
  };
}
