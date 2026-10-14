import type { MouseEvent } from "react";
import { useNavigate } from "react-router-dom";

/** A board row's or card's click handler: anywhere but its links, inputs
 *  and buttons (which handle their own clicks; cmd/middle-click on a link
 *  opens a tab) opens *href*. */
export function useRowNavigate(href: string) {
  const navigate = useNavigate();
  return (e: MouseEvent) => {
    if ((e.target as HTMLElement).closest("a, input, button")) return;
    navigate(href);
  };
}
