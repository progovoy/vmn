import { useRef, useState } from "react";
import { useJob } from "../components/ui";

export type ArchiveVerb = "archive" | "unarchive";
type Body = Record<string, unknown>;

/** `exp_archive`/`exp_unarchive` jobs, one per body and one at a time:
 *  *onDone* once the last succeeds, else the first failure as `archiveError`. */
export function useArchiveJob(ws: string, app: string, onDone: () => void) {
  const [error, setError] = useState<string | null>(null);
  const queue = useRef<{ verb: ArchiveVerb; bodies: Body[] }>({ verb: "archive", bodies: [] });
  const job = useJob((j) => {
    if (j.status !== "succeeded") {
      setError(`${j.command.join(" ") || "archive"} failed`);
      return;
    }
    const { verb, bodies } = queue.current;
    const next = bodies.shift();
    if (next) job.run(ws, app, `exp_${verb}`, next);
    else onDone();
  });
  const run = (verb: ArchiveVerb, body: Body | Body[]) => {
    const [first, ...rest] = Array.isArray(body) ? body : [body];
    if (!first) return;
    setError(null);
    queue.current = { verb, bodies: rest };
    job.run(ws, app, `exp_${verb}`, first);
  };
  return { run, archiving: job.job?.status === "running", archiveError: error ?? job.error };
}
