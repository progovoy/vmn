/** An ARIA tablist with one tab stop: a click opens a tab, the arrow keys
 *  (Home/End) move to and open one. The board's view switcher and the job
 *  page's tabs. */
import type { KeyboardEvent, ReactNode } from "react";
import { keyTarget } from "../hooks/useRovingToolbar";

export default function Tabs<T extends string>({ tabs, tab, onTab, label, className, panelId, tabId, render }: {
  tabs: readonly T[]; tab: T; onTab: (tab: T) => void;
  /** The tablist's accessible name. */
  label: string; className: string;
  /** The panel every tab controls. */
  panelId: string; tabId: (tab: T) => string;
  render: (tab: T) => ReactNode;
}) {
  const onKeyDown = (e: KeyboardEvent<HTMLElement>) => {
    const next = keyTarget(e.key, tabs.indexOf(tab), tabs.length);
    if (next === null) return;
    e.preventDefault();
    onTab(tabs[next]);
    e.currentTarget.querySelectorAll<HTMLElement>('[role="tab"]')[next]?.focus();
  };
  return (
    <div className={className} role="tablist" aria-label={label} onKeyDown={onKeyDown}>
      {tabs.map((t) => (
        <button
          key={t} type="button" role="tab" id={tabId(t)} aria-selected={t === tab} aria-controls={panelId}
          tabIndex={t === tab ? 0 : -1} className="board-tab" onClick={() => onTab(t)}
        >
          {render(t)}
        </button>
      ))}
    </div>
  );
}
