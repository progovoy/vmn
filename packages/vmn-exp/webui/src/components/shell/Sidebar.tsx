/** The contents of the shell's `<aside>` (plan 19 §1.2): wordmark, the
 *  workspace select, the App / Workspace / Server navs and the foot. */
import { useEffect, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { DOCS_URL, type ShellContext } from "../../shell/contracts";
import { navModel, type NavGroup, type NavItem } from "../../shell/navModel";
import { useAppStatus } from "../../shell/useShellData";
import { useAppExists } from "../../shell/useAppExists";
import { rememberApp, withLastApp } from "../../shell/lastApp";
import { CopyPath, wsLocation } from "../ui";
import AppSwitcher from "./AppSwitcher";
import { Icon } from "./icons";
import StatusRollup from "./StatusRollup";
import "./Sidebar.css";

type Nav = { onNavigate?: () => void };

function NavEntry({ item, onNavigate }: { item: NavItem } & Nav) {
  const body = <><Icon name={item.icon} /><span>{item.label}</span></>;
  if (!item.to) {
    return <span className="nav-item" aria-disabled="true" title={item.disabled}>{body}</span>;
  }
  return (
    <Link
      to={item.to} className="nav-item"
      aria-current={item.active ? "page" : undefined}
      state={onNavigate ? { focusMain: true } : undefined}
      onClick={onNavigate}
    >
      {body}
    </Link>
  );
}

/** The group's label is the nav's name, not a heading: the page's h1 comes first. */
function NavSection({ group, head, onNavigate }: { group: NavGroup; head?: ReactNode } & Nav) {
  return (
    <nav className="nav-group" aria-label={group.label}>
      <div className="nav-label" aria-hidden="true">{group.label}</div>
      {head}
      <ul>
        {group.items.map((item) => (
          <li key={item.id}><NavEntry item={item} onNavigate={onNavigate} /></li>
        ))}
      </ul>
    </nav>
  );
}

function WorkspaceSelect({ ctx, onNavigate }: { ctx: ShellContext } & Nav) {
  const navigate = useNavigate();
  const { workspace, workspaces } = ctx;
  return (
    <div className="nav-scope">
      <label className="sr-only" htmlFor="ws-select">Workspace</label>
      <div className="ws-select-wrap">
        <select
          id="ws-select"
          value={workspace?.name ?? ""}
          onChange={(e) => {
            navigate(`/ws/${e.target.value}`, { state: onNavigate ? { focusMain: true } : undefined });
            onNavigate?.();
          }}
        >
          <option value="" disabled>workspace…</option>
          {workspaces.map((w) => (
            <option key={w.name} value={w.name}>{`${w.name} — ${w.kind}`}</option>
          ))}
        </select>
        <span className="ws-select-chevron"><Icon name="chevron-down" /></span>
      </div>
      {workspace && <CopyPath text={wsLocation(workspace)} />}
    </div>
  );
}

function AppHead({ ctx, onNavigate }: { ctx: ShellContext } & Nav) {
  const status = useAppStatus(ctx.workspace?.name, ctx.appTag).data;
  return (
    <div className="nav-app">
      <AppSwitcher ws={ctx.workspace?.name} app={ctx.app} onNavigate={onNavigate} />
      {ctx.appBase && <StatusRollup status={status} href={(s) => `${ctx.appBase}${s}`} compact />}
    </div>
  );
}

function Foot({ ctx, footExtra }: { ctx: ShellContext; footExtra?: ReactNode }) {
  const { version, vmn_exp_version: expVersion } = ctx.meta ?? {};
  return (
    <div className="sidebar-foot">
      <div className="sidebar-versions">
        {expVersion && <span>{`vmn-exp ${expVersion}`}</span>}
        {version && <span>{`vmn ${version}`}</span>}
      </div>
      <a className="sidebar-docs" href={DOCS_URL} target="_blank" rel="noreferrer">
        Docs <Icon name="external" size={11} /><span className="sr-only"> (opens on GitHub)</span>
      </a>
      {footExtra}
    </div>
  );
}

const withoutApp = (ctx: ShellContext): ShellContext =>
  ({ ...ctx, appTag: undefined, app: undefined, appBase: undefined });

/** Remembers the URL's app once the server knows it; an app it does not know
 *  gives no app context. Returns *ctx* with the workspace's last app when the
 *  URL names none (or an unknown one). */
function useLastApp(ctx: ShellContext): ShellContext {
  const known = Boolean(ctx.workspace);
  const exists = useAppExists(known ? ctx.ws : undefined, ctx.appTag);
  useEffect(() => {
    if (exists && ctx.ws && ctx.appTag) rememberApp(ctx.ws, ctx.appTag);
  }, [exists, ctx.ws, ctx.appTag]);
  return withLastApp(exists === false ? withoutApp(ctx) : ctx);
}

export default function Sidebar({ ctx: urlCtx, onNavigate, footExtra }: {
  ctx: ShellContext; onNavigate?: () => void; footExtra?: ReactNode;
}) {
  const ctx = useLastApp(urlCtx);
  const [app, ...rest] = navModel(ctx);
  return (
    <>
      <Link
        to="/" className="sidebar-brand" onClick={onNavigate}
        state={onNavigate ? { home: true, focusMain: true } : { home: true }}
      >
        <span className="logo" aria-hidden="true">v</span>
        <span className="word">vmn<span>-exp</span></span>
      </Link>
      <WorkspaceSelect ctx={ctx} onNavigate={onNavigate} />
      <NavSection group={app} head={<AppHead ctx={ctx} onNavigate={onNavigate} />} onNavigate={onNavigate} />
      {rest.map((g) => <NavSection key={g.id} group={g} onNavigate={onNavigate} />)}
      <Foot ctx={ctx} footExtra={footExtra} />
    </>
  );
}
