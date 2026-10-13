/** A leaderboard header's column menu: the keyboard (and screen-reader) way
 *  to do what the header's click, drag and the column picker do. */
import { useCallback, useRef, useState, type KeyboardEvent, type SyntheticEvent } from "react";
import { createPortal } from "react-dom";
import { useDismiss } from "../hooks/useDismiss";
import { useMenuKeys } from "../hooks/useMenuKeys";
import "./ColumnMenu.css";

export interface MenuAction {
  label: string;
  run: () => void;
  disabled?: boolean;
}

const stop = (e: SyntheticEvent) => e.stopPropagation();
const MENU_WIDTH = 160;

/** The menu sits in a portal at the trigger, as the header cell clips. Its
 *  events stop at the menu: they must not sort, drag or move the rows. */
export default function ColumnMenu({ name, actions }: { name: string; actions: readonly MenuAction[] }) {
  const [at, setAt] = useState<{ top: number; left: number } | null>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const open = at !== null;
  const close = useCallback(() => setAt(null), []);
  useDismiss(open, close, menu, trigger);
  const onMenuKeys = useMenuKeys(open, menu, close);

  const toggle = (e: SyntheticEvent) => {
    e.stopPropagation();
    if (open) return close();
    const r = trigger.current!.getBoundingClientRect();
    setAt({ top: r.bottom + 4, left: Math.max(4, Math.min(r.left, window.innerWidth - MENU_WIDTH - 4)) });
  };
  const onKeyDown = (e: KeyboardEvent<HTMLElement>) => {
    onMenuKeys(e);
    // Escape travels on to useDismiss, which closes and refocuses the trigger.
    if (e.key !== "Escape") e.stopPropagation();
  };
  const choose = (a: MenuAction) => {
    close();
    trigger.current?.focus();
    a.run();
  };

  return (
    <>
      <button
        ref={trigger} type="button" className="th-menu" aria-label={`Column menu: ${name}`}
        aria-haspopup="menu" aria-expanded={open} title={`${name}: sort, hide, pin, move`}
        onClick={toggle} onMouseDown={stop} draggable={false}
        onDragStart={(e) => { e.preventDefault(); e.stopPropagation(); }}
      />
      {at && createPortal(
        <div
          ref={menu} role="menu" aria-label={`${name} column`} className="th-menu-pop"
          style={{ top: at.top, left: at.left, minWidth: MENU_WIDTH }}
          onKeyDown={onKeyDown} onClick={stop} onMouseDown={stop}
        >
          {actions.map((a) => (
            <button key={a.label} type="button" role="menuitem" disabled={a.disabled} onClick={() => choose(a)}>
              {a.label}
            </button>
          ))}
        </div>,
        document.body,
      )}
    </>
  );
}
