import type { HttpError } from "./http";

/** What a failed job poll means. A 404 is "unknown": jobs live in the memory
 *  of the replica that started them, so a restart or another replica (or,
 *  since jobs are scoped, another workspace) forgets the job, which may well
 *  be running or done. Anything else is a real error. */
export function pollOutcome(error: unknown): "unknown" | "error" {
  return (error as HttpError | null)?.status === 404 ? "unknown" : "error";
}
