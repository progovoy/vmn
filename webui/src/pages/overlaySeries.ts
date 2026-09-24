/** Loading (and re-polling) the overlay's runs: one batch request for every
 *  run's series, falling back to one detail request per run on servers that
 *  predate the batch endpoint. */
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { fetchRunStatuses, fetchSeriesBatch } from "../apiSeries";
import { usePolling } from "../hooks/usePolling";
import type { RunStatus, SeriesPoint } from "../types";
import { pollIntervalMs } from "../util";
import { capSeries, runOrigin } from "../util/chartData";

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

async function loadEach(ws: string, app: string, runs: string[]): Promise<OverlayData> {
  const details = await Promise.all(runs.map((v) => api.experiment(ws, app, v, OVERLAY_POINTS)));
  return {
    runs: details.map((d, i) => toRun(runs[i], capSeries(d.series, OVERLAY_POINTS), d.status)),
    missing: [],
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
  const [data, setData] = useState<OverlayData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const batchAvailable = useRef(true);
  const current = useRef(runs);
  current.current = runs;

  const load = useCallback(async () => {
    if (runs.length === 0) return;
    let next: OverlayData | null = null;
    if (batchAvailable.current) {
      next = await loadBatch(ws, app, runs).catch((e) => {
        // Only a server without the endpoint turns batching off for good; any
        // other failure falls back for this load and retries the batch next poll.
        if (e?.status === 404 || e?.status === 405) batchAvailable.current = false;
        return null;
      });
    }
    try {
      next ??= await loadEach(ws, app, runs);
      if (current.current === runs) setData(next);
    } catch (e) {
      // A failed poll keeps the charts already on screen.
      if (current.current === runs) setError((prev) => prev ?? String(e));
    }
  }, [ws, app, runs]);

  useEffect(() => {
    setData(null);
    setError(null);
    load();
  }, [load]);

  const interval = data ? pollInterval(data.runs) : null;
  usePolling(load, interval ?? 0, interval !== null);
  return { data, error };
}
