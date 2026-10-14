import { useState } from "react";
import { useJob } from "../components/ui";

export type ArchiveVerb = "archive" | "unarchive";

/** An `exp_archive`/`exp_unarchive` job: *onDone* once it succeeds, else
 *  its failure as `archiveError`. */
export function useArchiveJob(ws: string, app: string, onDone: () => void) {
  const [error, setError] = useState<string | null>(null);
  const job = useJob((j) => {
    if (j.status === "succeeded") onDone();
    else setError(`${j.command.join(" ") || "archive"} failed`);
  });
  const run = (verb: ArchiveVerb, body: Record<string, unknown>) => {
    setError(null);
    job.run(ws, app, `exp_${verb}`, body);
  };
  return { run, archiving: job.job?.status === "running", archiveError: error ?? job.error };
}
