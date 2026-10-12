import type { KeyboardEvent, ReactNode } from "react";
import { BOARD_TABS, type BoardTab } from "../hooks/useLeaderboardView";

export const BOARD_PANEL_ID = "board-panel";
export const boardTabId = (tab: BoardTab) => `board-tab-${tab}`;

const ICON_PROPS = { width: 14, height: 14, viewBox: "0 0 16 16", "aria-hidden": true } as const;

const TABS: Record<BoardTab, { label: string; icon: ReactNode }> = {
  runs: {
    label: "Runs",
    icon: (
      <svg {...ICON_PROPS}>
        <rect x="1.5" y="2.5" width="13" height="11" rx="1.5" fill="none" stroke="currentColor" strokeWidth="1.4" />
        <path d="M1.5 6.5h13M1.5 10h13M6 6.5v7" stroke="currentColor" strokeWidth="1.4" />
      </svg>
    ),
  },
  charts: {
    label: "Charts",
    icon: (
      <svg {...ICON_PROPS}>
        <path d="M2 14h12" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
        <rect x="3" y="8" width="2.4" height="4.5" rx="0.6" fill="currentColor" />
        <rect x="6.8" y="4" width="2.4" height="8.5" rx="0.6" fill="currentColor" />
        <rect x="10.6" y="6" width="2.4" height="6.5" rx="0.6" fill="currentColor" />
      </svg>
    ),
  },
};

/** Arrow keys step (and wrap), Home/End jump; the target tab opens. */
function keyTarget(key: string, at: number): number | null {
  const n = BOARD_TABS.length;
  if (key === "ArrowRight") return (at + 1) % n;
  if (key === "ArrowLeft") return (at - 1 + n) % n;
  if (key === "Home") return 0;
  if (key === "End") return n - 1;
  return null;
}

/** The board's view switcher (Runs | Charts), right above the board: an
 *  ARIA tablist with one tab stop; the arrow keys move and open a tab. */
export default function BoardTabs({ tab, onTab }: { tab: BoardTab; onTab: (tab: BoardTab) => void }) {
  const onKeyDown = (e: KeyboardEvent<HTMLElement>) => {
    const next = keyTarget(e.key, BOARD_TABS.indexOf(tab));
    if (next === null) return;
    e.preventDefault();
    onTab(BOARD_TABS[next]);
    e.currentTarget.querySelectorAll<HTMLElement>('[role="tab"]')[next]?.focus();
  };
  return (
    <div className="board-tabs" role="tablist" aria-label="Board view" onKeyDown={onKeyDown}>
      {BOARD_TABS.map((t) => (
        <button
          key={t} role="tab" id={boardTabId(t)} aria-selected={t === tab} aria-controls={BOARD_PANEL_ID}
          tabIndex={t === tab ? 0 : -1} className="board-tab" onClick={() => onTab(t)}
        >
          {TABS[t].icon}
          {TABS[t].label}
        </button>
      ))}
    </div>
  );
}
