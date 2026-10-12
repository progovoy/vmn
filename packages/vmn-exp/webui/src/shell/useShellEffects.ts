/** The App shell's side effects (plan 19 §1.1, §1.4): the ⌘K hotkey, what a
 *  route change announces, remembers and focuses, and the workspace list's
 *  revalidation around home. */
import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useLocation } from "react-router-dom";
import { pushRecent } from "../components/palette/recents";
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

/** The title's subject: `@54 lr-sweep-3` of `(2 stuck) @54 lr-sweep-3 · ml_app — vmn-exp`. */
export function titleSubject(title: string): string {
  return title.replace(/ — vmn-exp$/, "").replace(/^\(\d+ stuck\) /, "").split(" · ")[0];
}

const RECENT_KIND: Partial<Record<RouteId, string>> = { run: "run", experiments: "app", apps: "ws" };
const UNREMEMBERED = new Set<RouteId>(["not-found", "sign-in"]);

/** On a pathname change: the new title goes to the live region, and focus
 *  moves to main only after a palette or drawer navigation (`state.focusMain`),
 *  so a mouse user never sees it jump. The destination joins ⌘K's Recent. */
export function useRouteAnnouncer(title: string, routeId: RouteId): string {
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

  // The label follows the title, which may improve once a run's name loads.
  const subject = titleSubject(title);
  useEffect(() => {
    if (UNREMEMBERED.has(routeId)) return;
    pushRecent({ label: subject, to: location.pathname + location.search, kind: RECENT_KIND[routeId] ?? "page" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.pathname, subject, routeId]);

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
