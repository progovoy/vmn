import type { RunState } from "../types";
import { fmtDuration, relTime } from "../util";

/** Extra detail worth carrying in the pill's accessible label — the numbers
 *  that explain *why* a run is in this state. */
function describe(
  status: RunState,
  exitCode: number | null | undefined,
  durationSec: number | null | undefined,
  staleSec: number | null | undefined
): string {
  switch (status) {
    case "running":
      return durationSec != null
        ? `running for ${fmtDuration(durationSec)}`
        : "running";
    case "stuck":
      return staleSec != null
        ? `stuck — no heartbeat for ${fmtDuration(staleSec)}`
        : "stuck — the runner stopped reporting";
    case "failed":
      return exitCode != null ? `failed — exit ${exitCode}` : "failed";
    case "succeeded":
      return durationSec != null
        ? `succeeded in ${fmtDuration(durationSec)}`
        : "succeeded";
    default:
      return "created — no run started yet";
  }
}

/** Colored pill for a run's job status. `running` pulses; `stuck` carries a
 *  warning glyph so a dead runner never reads as a live one; a waiting run
 *  its process handed back (`released_at`, plan 28 API2) says so. */
export default function StatusPill({ status, exitCode, durationSec, staleSec, errorSummary, releasedAt }: {
  status: RunState;
  exitCode?: number | null;
  durationSec?: number | null;
  staleSec?: number | null;
  /** What ended a failed run — appended to its tooltip. */
  errorSummary?: string | null;
  /** The run's last release; shown only while it waits. */
  releasedAt?: string | null;
}) {
  const released = status === "created" && !!releasedAt;
  const base = released
    ? `waiting — released ${relTime(releasedAt)}`
    : describe(status, exitCode, durationSec, staleSec);
  const label = status === "failed" && errorSummary ? `${base} — ${errorSummary}` : base;
  return (
    <span className={`status-pill ${status}`} title={label} aria-label={label}>
      <span className="dot" />
      {status === "stuck" && <span className="warn">⚠</span>}
      {status}
      {released && " · released"}
    </span>
  );
}
