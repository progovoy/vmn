/** The sidebar as an off-canvas drawer below 900px (plan 19 §1.10). While
 *  closed the drawer is inert; while open the page beside it is. Esc, a veil
 *  click or a navigation closes it. */
import { useCallback, useEffect, useRef, useState, type RefObject } from "react";
import { useLocation } from "react-router-dom";
import { useMediaQuery } from "./useMediaQuery";

const NARROW = "(max-width: 899px)";

export function setInert(el: HTMLElement | null, on: boolean) {
  if (on) el?.setAttribute("inert", "");
  else el?.removeAttribute("inert");
}

export interface Drawer {
  narrow: boolean;
  open: boolean;
  toggle: () => void;
  close: () => void;
  sidebarRef: RefObject<HTMLElement>;
  mainRef: RefObject<HTMLDivElement>;
}

export function useDrawer(): Drawer {
  const narrow = useMediaQuery(NARROW);
  const [open, setOpen] = useState(false);
  const sidebarRef = useRef<HTMLElement>(null);
  const mainRef = useRef<HTMLDivElement>(null);
  const opener = useRef<HTMLElement | null>(null);
  const { pathname } = useLocation();
  const isOpen = open && narrow;

  const wasOpen = useRef(false);
  const close = useCallback(() => setOpen(false), []);
  const toggle = useCallback(() => {
    if (open) return close();
    opener.current = document.activeElement as HTMLElement | null;
    setOpen(true);
  }, [open, close]);

  // A navigation (or widening the window) closes it; focus stays where the
  // navigation puts it, not on the menu button.
  useEffect(() => {
    opener.current = null;
    setOpen(false);
  }, [pathname, narrow]);

  // The one writer of inert. Closing hands focus back to whatever opened the
  // drawer, after the page is un-inerted: a browser will not focus inside an
  // inert subtree. (A navigation or a resize has cleared the opener already.)
  useEffect(() => {
    setInert(sidebarRef.current, narrow && !isOpen);
    setInert(mainRef.current, isOpen);
    if (isOpen) sidebarRef.current?.querySelector<HTMLElement>("nav a[href]")?.focus();
    else if (wasOpen.current) {
      if (opener.current?.isConnected) opener.current.focus();
      opener.current = null;
    }
    wasOpen.current = isOpen;
  }, [narrow, isOpen]);

  useEffect(() => {
    if (!isOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [isOpen, close]);

  return { narrow, open: isOpen, toggle, close, sidebarRef, mainRef };
}
