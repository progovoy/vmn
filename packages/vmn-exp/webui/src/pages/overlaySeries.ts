/** Loading (and re-polling) the overlay's runs: one batch request for every
 *  run's series, plus their status rows. */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchRunStatuses, fetchSeriesBatch } from "../apiSeries";
import { usePolling } from "../hooks/usePolling";
import { withSignal } from "../requestScope";
import type { ExperimentRow, SeriesPoint } from "../types";
import { pollIntervalMs } from "../util";
import { runOrigin } from "../util/chartData";

/** Per-metric point budget per run once several runs share a chart. */
export const OVERLAY_POINTS = 1000;

type Series = Record<string, SeriesPoint[]>;

export interface OverlayRunData {
  key: string;
  series: Series;
  /** This run's own clock start, for the "relative" x axis. */
  origin: number;
  status: string | null;
  heartbeatSec: number | null;
  /** The run's `@N`, name, kind and inner runs, for naming it off the chart. */
  idx?: number | null;
  name?: string | null;
  kind?: ExperimentRow["kind"];
  children?: string[];
}

export interface OverlayData {
  runs: OverlayRunData[];
  missing: string[];
  /** Declared x-axis metric per metric; the first run declaring one wins. */
  stepMetrics: Record<string, string>;
}

function mergeStepMetrics(perRun: Record<string, Record<string, string>> = {}, runs: string[]) {
  const merged: Record<string, string> = {};
  for (const v of runs) {
    for (const [m, x] of Object.entries(perRun[v] ?? {})) merged[m] ??= x;
  }
  return merged;
}

function toRun(key: string, series: Series, row?: Partial<ExperimentRow> | null): OverlayRunData {
  return {
    key,
    series,
    origin: runOrigin(series, row?.started_at),
    status: row?.status ?? null,
    heartbeatSec: row?.heartbeat_interval_sec ?? null,
    idx: row?.idx ?? null,
    name: row?.name ?? null,
    kind: row?.kind,
    children: row?.children ?? [],
  };
}

async function loadBatch(ws: string, app: string, runs: string[], maxPoints: number): Promise<OverlayData> {
  const [batch, statuses] = await Promise.all([
    fetchSeriesBatch(ws, app, runs, null, maxPoints),
    // Rows drive polling, the relative-time origin and run labels: best effort.
    fetchRunStatuses(ws, app, runs).catch(() => ({} as Record<string, Partial<ExperimentRow>>)),
  ]);
  return {
    runs: runs.filter((v) => batch.series[v]).map((v) => toRun(v, batch.series[v], statuses[v])),
    missing: batch.missing ?? [],
    stepMetrics: mergeStepMetrics(batch.step_metrics, runs),
  };
}

/** Refresh cadence while runs are live: the fastest heartbeat among them. */
function pollInterval(runs: OverlayRunData[]): number | null {
  const live = runs.filter((r) => r.status === "running");
  if (live.length === 0) return null;
  const beats = live.map((r) => r.heartbeatSec).filter((s): s is number => s != null);
  return pollIntervalMs(beats.length ? Math.min(...beats) : null);
}

/** Callers asking for the same runs and budget share one request. */
export function useOverlaySeries(ws: string, app: string, runs: string[], maxPoints = OVERLAY_POINTS) {
  const client = useQueryClient();
  const query = useQuery<OverlayData>({
    queryKey: ["overlay", ws, app, runs, maxPoints],
    queryFn: ({ signal }) => withSignal(signal, () => loadBatch(ws, app, runs, maxPoints)),
    enabled: runs.length > 0,
  }, client);
  const data = query.data ?? null;
  const interval = data ? pollInterval(data.runs) : null;
  // A failed poll keeps the charts already on screen.
  usePolling(() => query.refetch(), interval ?? 0, interval !== null);
  return { data, error: query.error ? String(query.error) : null };
}
