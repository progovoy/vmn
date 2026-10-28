/** A page's default team view (plan 28 P4), applied on first landing: once
 *  the app's views are known, when the URL carries no view params, and only
 *  once per *sessionKey* in the tab, so it never fights what the user did
 *  since (cleared the filters, came Back to the page). */
import { useEffect, useRef } from "react";
import { useLocation } from "react-router-dom";
import { defaultViewOf, hasViewParams, type TeamView, type ViewPage } from "../util/teamViews";

const STORE_PREFIX = "vmn_default_view_applied:";

function appliedBefore(key: string): boolean {
  try { return sessionStorage.getItem(STORE_PREFIX + key) !== null; } catch { return false; }
}

function noteApplied(key: string) {
  try { sessionStorage.setItem(STORE_PREFIX + key, "1"); } catch { /* applied this mount only */ }
}

/** *views*: undefined while the app's status loads. */
export function useDefaultView(
  sessionKey: string, views: readonly TeamView[] | undefined, page: ViewPage, apply: (search: string) => void,
) {
  const { search } = useLocation();
  const decided = useRef(false);
  useEffect(() => {
    if (decided.current || views === undefined) return;
    decided.current = true;
    const view = defaultViewOf(views, page);
    if (!view || hasViewParams(search) || appliedBefore(sessionKey)) return;
    noteApplied(sessionKey);
    apply(view.search);
  }, [views, page, search, sessionKey, apply]);
}
