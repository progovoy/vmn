/** A page's freshness (plan 23 S5): pushed by the app's (or *scope*'s) live
 *  events, else polled at the cadence *heartbeatSec* can move the payload at.
 *  Neither while disabled; *poll* (default on) gates only the polling, so a
 *  board listens while nothing runs yet. Returns whether the stream is open. */
import { pollIntervalMs } from "../util";
import { useLiveScope, type LiveChange } from "./useLiveScope";
import { usePolling } from "./usePolling";

export function useLiveOrPoll({ ws, app, scope, enabled, heartbeatSec, refresh, onChange = refresh, poll = true }: {
  ws: string; app: string; scope?: string; enabled: boolean;
  heartbeatSec: number | null | undefined;
  refresh: () => unknown;
  /** What a change refetches (default: *refresh*). */
  onChange?: (change?: LiveChange) => unknown;
  poll?: boolean;
}): boolean {
  const { connected } = useLiveScope({ ws, app, scope, enabled, onChange });
  usePolling(refresh, pollIntervalMs(heartbeatSec), enabled && poll && !connected);
  return connected;
}
