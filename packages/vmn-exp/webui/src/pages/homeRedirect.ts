/** Where `/` sends a first visit (plan 19 §1.8): back to where sign-in started,
 *  else straight to the only app or the only workspace. Pure. */
import { appTag } from "../http";
import type { AppRow, Workspace } from "../types";

export type HomeDecision = { to: string } | "wait" | null;

/** A same-origin path, never `//host` (which the browser reads as another origin). */
export function validReturnTo(value: string | null): string | null {
  return value && value.startsWith("/") && !value.startsWith("//") ? value : null;
}

/** Only the entry the browser landed on redirects: a home link (`state.home`)
 *  or any later navigation shows the workspaces. */
export function isFirstEntry({ key, state }: { key: string; state: unknown }): boolean {
  return key === "default" && !(state as { home?: boolean } | null)?.home;
}

/** *apps* are the only workspace's, once loaded. "wait" = not decidable yet. */
export function homeRedirect({ location, returnTo, workspaces, apps }: {
  location: { key: string; state: unknown };
  returnTo: string | null;
  workspaces?: Workspace[];
  apps?: AppRow[];
}): HomeDecision {
  if (!isFirstEntry(location)) return null;
  const back = validReturnTo(returnTo);
  if (back) return { to: back };
  if (!workspaces) return "wait";
  if (workspaces.length !== 1) return null;
  if (!apps) return "wait";
  const ws = workspaces[0].name;
  if (apps.length === 1) return { to: `/ws/${ws}/app/${appTag(apps[0].name)}` };
  return apps.length > 1 ? { to: `/ws/${ws}` } : null;
}
