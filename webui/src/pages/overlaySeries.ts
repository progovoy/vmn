/** Loading (and re-polling) the overlay's runs: one batch request for every
 *  run's series, plus their status rows. */
import { useQuery } from "@tanstack/react-query";
import { fetchRunStatuses, fetchSeriesBatch } from "../apiSeries";
import { usePolling } from "../hooks/usePolling";
import { useAppQueryClient } from "../queryClient";
import { withSignal } from "../requestScope";
import type { RunStatus, SeriesPoint } from "../types";
import { pollIntervalMs } from "../util";
import { runOrigin } from "../util/chartData";

/** Per-metric point budget per run once several runs share a chart. */
const OVERLAY_POINTS = 1000;

type Series = Record<string, SeriesPoint[]>;

export interface OverlayRunData {
  key: string;
  series: Series;
  /** This run's own clock start, for the "relative" x axis. */
  origin: number;
  status: string | null;
  heartbeatSec: number | null;
}

export interface OverlayData {
  runs: OverlayRunData[];
  missing: string[];
}

function toRun(key: string, series: Series, status?: Partial<RunStatus> | null): OverlayRunData {
  return {
    key,
    series,
    origin: runOrigin(series, status?.started_at),
    status: status?.status ?? null,
    heartbeatSec: status?.heartbeat_interval_sec ?? null,
  };
}

async function loadBatch(ws: string, app: string, runs: string[]): Promise<OverlayData> {
  const [batch, statuses] = await Promise.all([
    fetchSeriesBatch(ws, app, runs, null, OVERLAY_POINTS),
    // Status only drives polling and the relative-time origin: best effort.
    fetchRunStatuses(ws, app, runs).catch(() => ({} as Record<string, Partial<RunStatus>>)),
  ]);
  return {
    runs: runs.filter((v) => batch.series[v]).map((v) => toRun(v, batch.series[v], statuses[v])),
    missing: batch.missing ?? [],
  };
}

/** Refresh cadence while runs are live: the fastest heartbeat among them. */
function pollInterval(runs: OverlayRunData[]): number | null {
  const live = runs.filter((r) => r.status === "running");
  if (live.length === 0) return null;
  const beats = live.map((r) => r.heartbeatSec).filter((s): s is number => s != null);
  return pollIntervalMs(beats.length ? Math.min(...beats) : null);
}

export function useOverlaySeries(ws: string, app: string, runs: string[]) {
  const client = useAppQueryClient();
  const query = useQuery<OverlayData>({
    queryKey: ["overlay", ws, app, runs],
    queryFn: ({ signal }) => withSignal(signal, () => loadBatch(ws, app, runs)),
    enabled: runs.length > 0,
  }, client);
  const data = query.data ?? null;
  const interval = data ? pollInterval(data.runs) : null;
  // A failed poll keeps the charts already on screen.
  usePolling(() => query.refetch(), interval ?? 0, interval !== null);
  return { data, error: query.error ? String(query.error) : null };
}
