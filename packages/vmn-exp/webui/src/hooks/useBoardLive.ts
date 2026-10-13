/** A board's freshness (plan 23 S5): pushed by the app's (or *scope*'s)
 *  live events, which refresh its rows and facets; else, while a run is
 *  still in flight and not paused, polled at the cadence its heartbeat can
 *  actually move the status at. Grouped, *serverRunning* counts running
 *  rows the board has not loaded (plan 22 F4). */
import { useMemo } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { facetsQuery } from "../queries";
import type { ExperimentRow } from "../types";
import { pollIntervalMs } from "../util";
import { useLiveScope } from "./useLiveScope";
import { usePolling } from "./usePolling";

const ownRunning = (r: ExperimentRow) => r.status === "running";

export function useBoardLive({ ws, app, scope, paused, rows, serverRunning, refresh, isRunning = ownRunning }: {
  ws: string; app: string; scope?: string; paused: boolean;
  rows: readonly ExperimentRow[] | undefined;
  serverRunning: boolean;
  refresh: () => Promise<unknown>;
  /** Whether a row keeps the board live (default: its own status). */
  isRunning?: (r: ExperimentRow) => boolean;
}) {
  const client = useQueryClient();
  const { anyRunning, heartbeatSec } = useMemo(() => {
    let running = serverRunning;
    let fastest: number | null = null;
    for (const r of rows ?? []) {
      if (isRunning(r)) running = true;
      const hb = r.heartbeat_interval_sec;
      if (typeof hb === "number" && (fastest === null || hb < fastest)) fastest = hb;
    }
    return { anyRunning: running, heartbeatSec: fastest };
  }, [rows, serverRunning, isRunning]);
  const live = useLiveScope({
    ws, app, scope, enabled: !paused,
    onChange: () => Promise.all([
      refresh(),
      client.invalidateQueries({ queryKey: facetsQuery(ws, app).queryKey }),
    ]),
  });
  usePolling(refresh, pollIntervalMs(heartbeatSec), anyRunning && !paused && !live.connected);
  return anyRunning;
}
