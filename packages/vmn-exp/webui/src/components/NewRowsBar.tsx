/** The `N new · show` bar (plan 23 W6): while the reader is scrolled down
 *  or has rows selected, a live change does not reshuffle the board — its
 *  rows update in place and this bar says what waits; clicking it reloads
 *  page 1 and scrolls to the top. */
import type { MutableRefObject } from "react";
import type { BoardViewport } from "../hooks/useLeaderboardRows";
import type { HeldChange } from "../pages/leaderboardRefresh";
import { plural } from "../util";
import "./NewRowsBar.css";

export default function NewRowsBar({ pending, noun = "run", onShow }: {
  pending: HeldChange | null;
  noun?: string;
  onShow: () => void;
}) {
  if (!pending) return null;
  const what = pending.added ? plural(pending.added, `new ${noun}`) : "Order changed";
  return (
    <div className="new-rows-bar" role="status">
      <button type="button" onClick={onShow}>{`${what} · show`}</button>
    </div>
  );
}

/** Tells the rows behind *viewport* whether to hold (scrolled down, rows
 *  selected) and how to get back to the top: of *scroller*, else the window. */
export function useHeldViewport(
  viewport: MutableRefObject<BoardViewport> | undefined,
  scroller: MutableRefObject<HTMLElement | null>,
  selected: ReadonlySet<string>,
) {
  if (!viewport) return;
  viewport.current = {
    held: () => selected.size > 0 || (scroller.current ? scroller.current.scrollTop : window.scrollY) > 0,
    toTop: () => {
      if (scroller.current) scroller.current.scrollTop = 0;
      else window.scrollTo(0, 0);
    },
  };
}
