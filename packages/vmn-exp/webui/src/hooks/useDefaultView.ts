/** A page's default team view (plan 28 P4), applied once the app's views
 *  are known and the URL carries no view params: on every link to the bare
 *  page (a push: the nav link, from anywhere), and on a first landing that
 *  is no link (a reload, Back, a typed URL) only once per *sessionKey* in the
 *  tab. What the user did on the page (an in-place replace to a bare URL:
 *  cleared the filters, picked no view) and Back keep their URL. */
import { useEffect, useRef } from "react";
import { useLocation, useNavigationType } from "react-router-dom";
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
  const { search, key } = useLocation();
  const linked = useNavigationType() === "PUSH";
  // The location last decided on: each is decided once, the mount's first apart.
  const decided = useRef<string | null>(null);
  useEffect(() => {
    if (decided.current === key || views === undefined) return;
    const first = decided.current === null;
    decided.current = key;
    const view = defaultViewOf(views, page);
    if (!view || hasViewParams(search)) return;
    if (!linked && (!first || appliedBefore(sessionKey))) return;
    noteApplied(sessionKey);
    apply(view.search);
  }, [views, page, search, key, linked, sessionKey, apply]);
}
