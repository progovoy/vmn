/** The App shell's side effects (plan 19 §1.1, §1.4): the ⌘K hotkey, what a
 *  route change announces, remembers and focuses, and the workspace list's
 *  revalidation around home. */
import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useLocation } from "react-router-dom";
import { forgetRecent, pushRecent, recentKindOf } from "../components/palette/recents";
import { WORKSPACES_KEY } from "../queries";
import type { RouteId } from "./contracts";

/** ⌘K / Ctrl+K toggles the palette from anywhere. */
export function usePaletteHotkey(setOpen: Dispatch<SetStateAction<boolean>>) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((o) => !o);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setOpen]);
}

const UNREMEMBERED = new Set<RouteId>(["not-found", "sign-in"]);

/** On a pathname change: the new title goes to the live region, and focus
 *  moves to main only after a palette or drawer navigation (`state.focusMain`),
 *  so a mouse user never sees it jump. The destination joins ⌘K's Recent. */
export function useRouteAnnouncer(title: string, subject: string, routeId: RouteId, deadEnd = false): string {
  const location = useLocation();
  const [announced, setAnnounced] = useState("");
  const first = useRef(true);
  const titleNow = useRef(title);
  titleNow.current = title;

  useEffect(() => {
    if (first.current) { first.current = false; return; }
    setAnnounced(titleNow.current);
    if ((location.state as { focusMain?: boolean } | null)?.focusMain) {
      document.getElementById("main")?.focus();
    }
    // Only the pathname announces: a filter edit is no page change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.pathname]);

  // The label follows the subject, which may improve once a run's name loads;
  // a page that turns out missing or broken is dropped again.
  useEffect(() => {
    const to = location.pathname + location.search;
    if (deadEnd || UNREMEMBERED.has(routeId)) return forgetRecent(to);
    pushRecent({ label: subject, to, kind: recentKindOf(routeId) });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.pathname, subject, routeId, deadEnd]);

  return announced;
}

/** Revalidate the workspace list on entering or leaving home, where the
 *  attach form lives. */
export function useHomeRevalidation() {
  const client = useQueryClient();
  const atHome = useLocation().pathname === "/";
  const firstVisit = useRef(true);
  useEffect(() => {
    if (firstVisit.current) { firstVisit.current = false; return; }
    client.invalidateQueries({ queryKey: WORKSPACES_KEY });
  }, [atHome, client]);
}
