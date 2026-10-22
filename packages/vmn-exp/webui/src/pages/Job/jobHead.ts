/** What an outer run's page paints before its summary lands: the index's
 *  row of it (a board's cached row, else a one-row lookup), else its run
 *  detail. The row's `job` rollup carries the progress; without it the
 *  header shows no bar until the summary does. */
import type { JobPageSummary } from "../../apiJob";
import type { ExperimentDetail, ExperimentRow, RunState } from "../../types";
import { outerRunCount } from "../../util/outerRun";
import { summaryFromDetail, summaryFromRow } from "../runSummary";
import type { JobHeadSummary } from "./JobHeader";

export interface JobPageHead {
  head: JobHeadSummary;
  /** The job's own command and heartbeat cadence (Reproduce, the poll). */
  command: string[] | null;
  heartbeatSec: number | null;
}

export function jobHead(
  v: string, summary?: JobPageSummary, row?: ExperimentRow, detail?: ExperimentDetail,
): JobPageHead {
  const run = detail ? summaryFromDetail(detail) : row ? summaryFromRow(row) : null;
  const st = run?.status;
  const head = summary ?? {
    ...row?.job, verstr: v, name: run?.name ?? null, idx: run?.idx ?? null,
    status: st?.status ?? "created", tree_status: (st?.tree_status as RunState | undefined) ?? null,
    sweep: st?.sweep_planned != null, total: outerRunCount(row ?? st ?? {}),
  };
  return { head, command: st?.command ?? null, heartbeatSec: st?.heartbeat_interval_sec ?? null };
}
