import type { ReactNode } from "react";
import Tabs from "../components/Tabs";
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

/** The board's view switcher (Runs | Charts), right above the board. */
export default function BoardTabs({ tab, onTab }: { tab: BoardTab; onTab: (tab: BoardTab) => void }) {
  return (
    <Tabs
      tabs={BOARD_TABS} tab={tab} onTab={onTab} label="Board view" className="board-tabs"
      panelId={BOARD_PANEL_ID} tabId={boardTabId} render={(t) => <>{TABS[t].icon}{TABS[t].label}</>}
    />
  );
}
