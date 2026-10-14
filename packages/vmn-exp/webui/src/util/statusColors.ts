/** Each run status's colour (the --st-* tokens the pills wear) and its
 *  word: a created run is waiting. */
import type { RunState } from "../types";

export const STATUS_COLORS: Record<RunState | "waiting", string> = {
  running: "var(--st-running)", stuck: "var(--st-stuck)", failed: "var(--st-bad)",
  succeeded: "var(--st-good)", created: "var(--text-3)", waiting: "var(--text-3)",
};

export const statusLabel = (s: RunState) => (s === "created" ? "waiting" : s);

/** A status's colour, a dim one for a state the map lacks. */
export const statusColor = (s: string) => STATUS_COLORS[s as RunState] ?? "var(--text-3)";
