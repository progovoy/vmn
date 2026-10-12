/** The topbar's breadcrumb trail (plan 19 §1.4): ContextRoot first, the leaf
 *  as the current page (never a link), then "Copy as CLI". Below 900 px only
 *  the leaf shows, behind a back link to its parent. */
import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { useDismiss } from "../../hooks/useDismiss";
import type { CliCommand, Crumb } from "../../shell/contracts";
import { copyText } from "../../util";
import { Icon } from "./icons";
import "./Crumbs.css";

const COPIED_MS = 1500;

function Separator() {
  return <span className="crumb-sep"><Icon name="chevron-right" size={11} /></span>;
}

function CrumbBody({ crumb, leaf }: { crumb: Crumb; leaf: boolean }) {
  const { label, to, mono, title, run } = crumb;
  const cls = `crumb-text${mono ? " mono" : ""}`;
  const hint = title ?? label;
  if (!leaf && to) return <Link className={cls} to={to} title={hint}>{label}</Link>;
  if (!leaf) return <span className={cls} title={hint}>{label}</span>;
  if (run?.idx != null && run.name) {
    return (
      <span className="crumb-text" aria-current="page" title={hint}>
        <span className="mono">@{run.idx}</span> <span className="crumb-run-name">{run.name}</span>
      </span>
    );
  }
  return <span className={cls} aria-current="page" title={hint}>{label}</span>;
}

/** Arrow keys move between the menu items; Tab leaves (and closes) the menu. */
function menuKeys(e: KeyboardEvent<HTMLDivElement>, close: () => void) {
  if (e.key === "Tab") return close();
  const step = e.key === "ArrowDown" ? 1 : e.key === "ArrowUp" ? -1 : 0;
  if (!step) return;
  e.preventDefault();
  const items = Array.from(e.currentTarget.querySelectorAll<HTMLButtonElement>('[role="menuitem"]'));
  const at = items.indexOf(document.activeElement as HTMLButtonElement);
  items[(at + step + items.length) % items.length]?.focus();
}

/** The default command's copy button, a menu of the others, and a polite
 *  live region that announces the copy. */
function CopyCli({ cli }: { cli: CliCommand[] }) {
  const [copied, setCopied] = useState<"copied" | "no clipboard" | null>(null);
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const more = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const close = useCallback(() => setOpen(false), []);
  useDismiss(open, close, box, more);
  useEffect(() => {
    if (open) menu.current?.querySelector<HTMLButtonElement>('[role="menuitem"]')?.focus();
  }, [open]);
  useEffect(() => {
    if (!copied) return;
    const t = window.setTimeout(() => setCopied(null), COPIED_MS);
    return () => window.clearTimeout(t);
  }, [copied]);

  const copy = (command: string) =>
    copyText(command).then((ok) => setCopied(ok ? "copied" : "no clipboard"));
  const [first, ...rest] = cli;
  return (
    <div className="crumb-copy-box" ref={box}>
      <button
        type="button" className="crumb-copy" title={first.command}
        aria-label={`Copy as CLI: ${first.command}`} onClick={() => copy(first.command)}
      >
        <Icon name={copied === "copied" ? "check" : "copy"} size={13} />
      </button>
      {rest.length > 0 && (
        <button
          type="button" className="crumb-copy-more" ref={more} aria-label="More CLI commands"
          aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((o) => !o)}
        >
          <Icon name="chevron-down" size={11} />
        </button>
      )}
      {open && (
        <div
          className="crumb-copy-menu" role="menu" aria-label="CLI commands" ref={menu}
          onKeyDown={(e) => menuKeys(e, close)}
        >
          {rest.map((c) => (
            <button
              type="button" role="menuitem" key={c.command} className="mono"
              onClick={() => { close(); more.current?.focus(); copy(c.command); }}
            >
              {c.command}
            </button>
          ))}
        </div>
      )}
      <span className="crumb-live" role="status" aria-live="polite">{copied ?? ""}</span>
    </div>
  );
}

export default function Crumbs({ root, crumbs, cli }: {
  root?: ReactNode; crumbs: Crumb[]; cli: CliCommand[];
}) {
  const parent = crumbs.length > 1 ? crumbs[crumbs.length - 2] : undefined;
  return (
    <nav className="breadcrumbs" aria-label="Breadcrumb">
      {parent?.to && (
        <Link className="crumb-back" to={parent.to} aria-label={`Back to ${parent.label}`}>
          <Icon name="chevron-left" size={13} />
        </Link>
      )}
      <ol className="crumb-trail">
        {root && <li className="crumb crumb-root">{root}</li>}
        {crumbs.map((crumb, i) => {
          const leaf = i === crumbs.length - 1;
          return (
            <li key={`${i}-${crumb.label}`} className={`crumb${leaf ? " crumb-leaf" : ""}`}>
              {(root || i > 0) && <Separator />}
              <CrumbBody crumb={crumb} leaf={leaf} />
            </li>
          );
        })}
      </ol>
      {cli.length > 0 && <CopyCli key={cli.map((c) => c.command).join("\n")} cli={cli} />}
    </nav>
  );
}
