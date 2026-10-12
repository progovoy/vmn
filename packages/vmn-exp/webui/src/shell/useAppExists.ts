/** Whether an app exists, from two signals (plan 19 §1.6): the app list hides
 *  an app stamped within its 5 s server TTL, the status count does not. */
import { useApps } from "../queries";
import { usePolling } from "../hooks/usePolling";
import type { HttpError } from "../http";
import { useAppStatus } from "./useShellData";

/** One beat past the server's app-list TTL (APPS_TTL_SEC + 1). */
const MISSING_REFETCH_MS = 6_000;

const tagOf = (name: string) => name.replaceAll("/", "-");

/** `undefined` while either signal is still unknown (loading, network error). */
export function useAppExists(ws: string | undefined, tag: string | undefined): boolean | undefined {
  const apps = useApps(ws);
  const status = useAppStatus(ws, tag);
  const listed = apps.data?.some((a) => tagOf(a.name) === tag);
  let exists: boolean | undefined;
  if (listed || (status.data?.total ?? 0) > 0) exists = true;
  else if ((status.error as HttpError | null)?.status === 400) exists = false;
  else if (apps.data && status.data) exists = false;
  usePolling(() => apps.refetch(), MISSING_REFETCH_MS, exists === false);
  return exists;
}
