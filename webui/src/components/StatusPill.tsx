import type { RunState } from "../types";
import { fmtDuration } from "../util";

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
 *  warning glyph so a dead runner never reads as a live one. */
export default function StatusPill({ status, exitCode, durationSec, staleSec }: {
  status: RunState;
  exitCode?: number | null;
  durationSec?: number | null;
  staleSec?: number | null;
}) {
  const label = describe(status, exitCode, durationSec, staleSec);
  return (
    <span className={`status-pill ${status}`} title={label} aria-label={label}>
      <span className="dot" />
      {status === "stuck" && <span className="warn">⚠</span>}
      {status}
    </span>
  );
}
