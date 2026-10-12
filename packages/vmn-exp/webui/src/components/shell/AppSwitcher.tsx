/** The App group's switcher: a menu button listing the workspace's apps.
 *  The menu is `position: fixed` at the button, so the sidebar's scroll
 *  container never clips it. */
import { useCallback, useEffect, useRef, useState, type CSSProperties, type KeyboardEvent } from "react";
import { Link } from "react-router-dom";
import { appHref } from "../../util";
import { useDismiss } from "../../hooks/useDismiss";
import { useApps } from "../../queries";
import { Icon } from "./icons";

function AppMenu({ ws, app, style, onPick, onClose, drawer }: {
  ws: string; app?: string; style: CSSProperties; onPick: () => void; onClose: () => void; drawer: boolean;
}) {
  const apps = useApps(ws).data;
  const menuRef = useRef<HTMLDivElement>(null);
  // Focus moves into the menu once it has items: the current app, else the first.
  const loaded = apps !== undefined;
  useEffect(() => {
    const menu = menuRef.current;
    (menu?.querySelector<HTMLElement>("[aria-current=page]") ?? menu?.querySelector<HTMLElement>("[role=menuitem]"))
      ?.focus();
  }, [loaded]);
  // The menu is fixed at the button's old rect: close it once that moves.
  useEffect(() => {
    const onMove = (e: Event) => {
      if (!(e.target instanceof Node && menuRef.current?.contains(e.target))) onClose();
    };
    document.addEventListener("scroll", onMove, true);
    window.addEventListener("resize", onMove);
    return () => {
      document.removeEventListener("scroll", onMove, true);
      window.removeEventListener("resize", onMove);
    };
  }, [onClose]);
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Tab") return onClose();
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    e.preventDefault();
    const items = Array.from(e.currentTarget.querySelectorAll<HTMLElement>("[role=menuitem]"));
    const at = items.indexOf(document.activeElement as HTMLElement);
    const step = e.key === "ArrowDown" ? 1 : -1;
    items[(at + step + items.length) % items.length]?.focus();
  };
  return (
    <div ref={menuRef} className="app-menu" role="menu" aria-label={`Apps in ${ws}`} style={style} onKeyDown={onKeyDown}>
      {apps?.length === 0 && <div className="app-menu-empty">No apps in {ws} yet</div>}
      {apps?.map((a) => (
        <Link
          key={a.name} role="menuitem" className="app-menu-item mono"
          to={appHref(ws, a.name)}
          aria-current={a.name === app ? "page" : undefined}
          state={drawer ? { focusMain: true } : undefined}
          onClick={onPick}
        >
          {a.name}
        </Link>
      ))}
    </div>
  );
}

export default function AppSwitcher({ ws, app, onNavigate }: {
  ws?: string; app?: string; onNavigate?: () => void;
}) {
  const [style, setStyle] = useState<CSSProperties | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const open = style !== null;
  const close = useCallback(() => setStyle(null), []);
  useDismiss(open, close, rootRef, buttonRef);

  const toggle = () => {
    if (open) return close();
    const r = buttonRef.current!.getBoundingClientRect();
    setStyle({ top: r.bottom + 4, left: r.left, minWidth: r.width });
  };
  const pick = () => {
    close();
    onNavigate?.();
  };

  return (
    <div className="app-switcher" ref={rootRef}>
      <button
        ref={buttonRef} type="button" className={`app-switch${app ? " mono" : ""}`}
        aria-haspopup="menu" aria-expanded={open}
        disabled={!ws} title={ws ? undefined : "choose a workspace first"}
        onClick={toggle}
      >
        <span className="app-switch-name">{app ?? "choose app"}</span>
        <Icon name="chevron-down" />
      </button>
      {open && ws && (
        <AppMenu ws={ws} app={app} style={style} onPick={pick} onClose={close} drawer={Boolean(onNavigate)} />
      )}
    </div>
  );
}
