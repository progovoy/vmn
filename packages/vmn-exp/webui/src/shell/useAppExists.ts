/** Whether an app exists, from the server's status answer (plan 19 §1.6): a
 *  200 means a known app (with or without runs), a 404 `app_not_found` an
 *  unknown one, a 400 a tag that can't name an app at all. */
import type { HttpError } from "../http";
import { usePageScope } from "./usePageScope";
import { useAppStatus } from "./useShellData";

function missing(error: unknown): boolean {
  const e = error as HttpError | null;
  if (e?.status === 400) return true;
  return e?.status === 404 && (e.body as { code?: unknown } | undefined)?.code === "app_not_found";
}

/** `undefined` while the answer is unknown (loading, network error). */
export function useAppExists(ws: string | undefined, tag: string | undefined): boolean | undefined {
  const status = useAppStatus(ws, tag);
  if (status.data) return true;
  return missing(status.error) ? false : undefined;
}

/** A run can be created here: a known app in a writable git workspace (§1.6). */
export function useCanCreateRun(ws: string | undefined, tag: string | undefined): boolean {
  const exists = useAppExists(ws, tag);
  const scope = usePageScope(ws);
  return exists === true && !scope.readOnly && scope.isGit;
}
