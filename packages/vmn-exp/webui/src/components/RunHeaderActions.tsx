/** The run header's actions (plan 20 D8, F8): Reproduce ▾ (copy the restore/
 *  rerun/export commands; `vmn goto` through the job runner in a writable git
 *  workspace), Copy link, then the page's own actions (*children*). */
import { useCallback, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { appName as toAppName } from "../api";
import { useDismiss } from "../hooks/useDismiss";
import { useMenuKeys } from "../hooks/useMenuKeys";
import { storeUriOf } from "../shell/cliCommands";
import { usePageScope } from "../shell/usePageScope";
import { runHref } from "../util";
import { Icon } from "./shell/icons";
import { useCopied } from "./ui";
import { gotoCommand, reproduceCommands, rerunsQuery } from "./reproduceCommands";
import RunGotoDialog from "./RunGotoDialog";
import "./RunHeaderActions.css";

function MenuItem({ command, hint, onClick }: { command: string; hint: string; onClick: () => void }) {
  return (
    <button type="button" role="menuitem" className="repro-item" onClick={onClick}>
      <span className="mono repro-cmd">{command}</span>
      <span className="repro-hint">{hint}</span>
    </button>
  );
}

export default function RunHeaderActions({ ws, app, verstr, command, children }: {
  ws: string; app: string; verstr: string; command?: string[] | null; children?: ReactNode;
}) {
  const scope = usePageScope(ws);
  const [copied, copy] = useCopied();
  const [open, setOpen] = useState(false);
  const [goto, setGoto] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const close = useCallback(() => setOpen(false), []);
  useDismiss(open, close, box, trigger);
  const onMenuKey = useMenuKeys(open, menu, close);

  const appName = toAppName(app);
  const boardBase = `/ws/${ws}/app/${app}`;
  const hasCommand = !!command?.length;
  const commands = reproduceCommands(appName, verstr, { storeUri: storeUriOf(scope.workspace), hasCommand });
  const canGoto = scope.metaStatus === "ok" && !scope.readOnly
    && !!scope.workspace && scope.workspace.kind !== "store";
  const pick = (then: () => void) => { close(); trigger.current?.focus(); then(); };
  const endGoto = () => { setGoto(false); trigger.current?.focus(); };

  return (
    <div className="run-actions">
      <div className="repro-box" ref={box}>
        <button
          type="button" className="btn" ref={trigger} aria-haspopup="menu" aria-expanded={open}
          onClick={() => setOpen((o) => !o)}
        >
          Reproduce <Icon name="chevron-down" size={11} />
        </button>
        {open && (
          <div className="repro-menu" role="menu" aria-label="Reproduce" ref={menu} onKeyDown={onMenuKey}>
            {commands.map((c) => (
              <MenuItem key={c.verb} command={c.command} hint={c.hint} onClick={() => pick(() => void copy(c.command))} />
            ))}
            {hasCommand && (
              <Link role="menuitem" className="repro-link" onClick={close}
                to={`${boardBase}?q=${encodeURIComponent(rerunsQuery(verstr))}`}>
                reruns →
              </Link>
            )}
            {canGoto && (
              <MenuItem command={`${gotoCommand(appName, verstr)} …`} hint="run it here, after you confirm"
                onClick={() => pick(() => setGoto(true))} />
            )}
          </div>
        )}
      </div>
      <button type="button" className="btn" aria-label="Copy link"
        onClick={() => void copy(`${window.location.origin}${runHref(boardBase, verstr)}`)}>
        <Icon name={copied === "copied" ? "check" : "copy"} size={13} /> Copy link
      </button>
      <span className="repro-live" role="status" aria-live="polite">{copied ?? ""}</span>
      {children}
      {goto && (
        <RunGotoDialog ws={ws} app={app} verstr={verstr} command={gotoCommand(appName, verstr)} onClose={endGoto} />
      )}
    </div>
  );
}
