/** Who the browser is to this server, and whether it can reach it at all.
 *  Replaces the old pulsing `local` chip; it never animates. */
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import type { ShellContext } from "../../shell/contracts";
import { useMeta } from "../../queries";
import { useDismiss } from "../../hooks/useDismiss";
import { copyText } from "../../util";
import { Icon } from "./icons";
import "./Topbar.css";

export const isLoopback = (hostname: string) =>
  hostname === "localhost" || hostname === "::1" || hostname === "[::1]"
  || /^127\.\d+\.\d+\.\d+$/.test(hostname);

type MenuKind = "sign-out" | "user";
interface Chip { text: string; title?: string; bad?: boolean; menu?: MenuKind }

function chipOf(ctx: ShellContext, forbiddenDetail: string | undefined): Chip | null {
  const { meta, metaStatus } = ctx;
  if (metaStatus === "loading") return null;
  if (metaStatus === "unauthorized") return { text: "not signed in" };
  if (metaStatus === "forbidden") return { text: "no access", title: forbiddenDetail, menu: "sign-out" };
  if (metaStatus === "unreachable") return { text: "server unreachable", title: "retrying…", bad: true };
  if (!ctx.authEnabled) {
    const { hostname, host } = window.location;
    return { text: isLoopback(hostname) ? "local" : host, title: `vmn-exp ui on ${host}: no sign-in` };
  }
  const principal = meta?.principal;
  if (!principal) return { text: "not signed in" };
  if (principal.id === "static-token") return { text: `token · ${meta?.role ?? "admin"}`, menu: "sign-out" };
  return { text: ctx.role ? `${principal.name} · ${ctx.role}` : principal.name, menu: "user" };
}

function ChipText({ chip }: { chip: Chip }) {
  return (
    <>
      {chip.bad && <Icon name="close" size={12} />}
      <span className="id-text">{chip.text}</span>
      <span className="id-initial" aria-hidden="true">{chip.text.charAt(0)}</span>
    </>
  );
}

/** The menu pattern's keys: arrows wrap, Home/End jump, Tab leaves (and closes). */
function onMenuKey(e: KeyboardEvent<HTMLDivElement>, close: () => void) {
  if (e.key === "Tab") return close();
  const items = [...e.currentTarget.querySelectorAll<HTMLElement>('[role="menuitem"]')];
  const at = items.indexOf(document.activeElement as HTMLElement);
  const to = { ArrowDown: at + 1, ArrowUp: at - 1, Home: 0, End: items.length - 1 }[e.key];
  if (to === undefined) return;
  e.preventDefault();
  items[(to + items.length) % items.length]?.focus();
}

function ChipMenu({ chip, ctx, onSignOut }: { chip: Chip; ctx: ShellContext; onSignOut: () => void }) {
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const close = () => setOpen(false);
  useDismiss(open, close, wrap, trigger);
  useEffect(() => {
    if (open) wrap.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus();
  }, [open]);
  const login = `vmn-exp login --server ${window.location.origin}`;
  return (
    <div className="id-wrap" ref={wrap}>
      <button
        ref={trigger} type="button" className="id-chip" title={chip.title}
        aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((o) => !o)}
      >
        <ChipText chip={chip} />
        <Icon name="chevron-down" size={11} />
      </button>
      {open && (
        <div className="id-pop">
          {chip.menu === "user" && (
            <ul className="id-roles" aria-label="Workspace roles">
              {ctx.workspaces.map((w) => (
                <li key={w.name}>
                  <span className="mono">{w.name}</span>
                  <span className="id-role">{w.role ?? "no role"}</span>
                </li>
              ))}
            </ul>
          )}
          <div role="menu" aria-label="Account" onKeyDown={(e) => onMenuKey(e, close)}>
            {chip.menu === "user" && (
              <button type="button" role="menuitem" onClick={() => { void copyText(login); close(); }}>
                Copy CLI login
              </button>
            )}
            <button type="button" role="menuitem" onClick={() => { close(); onSignOut(); }}>
              Sign out
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export default function IdentityChip({ ctx, onSignOut }: { ctx: ShellContext; onSignOut: () => void }) {
  const metaError = useMeta().error as Error | null;
  const chip = chipOf(ctx, metaError?.message);
  if (!chip) return null;
  if (chip.menu) return <ChipMenu chip={chip} ctx={ctx} onSignOut={onSignOut} />;
  return (
    <span className={`id-chip${chip.bad ? " bad" : ""}`} title={chip.title}>
      <ChipText chip={chip} />
    </span>
  );
}
