/** The dashboard shell (plan 19 §1.1): skip link, the sidebar (a drawer below
 *  900px), the topbar with crumbs, an app's stale-data banner, the page
 *  outlet behind the sign-in gate,
 *  ⌘K, and a live region that reads each new page's title. */
import { useQueryClient } from "@tanstack/react-query";
import { useLayoutEffect, useRef, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import AuthGate from "./auth/AuthGate";
import { signOut } from "./auth/authState";
import CommandPalette from "./components/CommandPalette";
import ErrorBoundary from "./components/ErrorBoundary";
import ThemeToggle from "./components/ThemeToggle";
import SelectionTrayHost from "./pages/SelectionTrayHost";
import ContextRoot from "./components/shell/ContextRoot";
import Crumbs from "./components/shell/Crumbs";
import FreshnessBanner from "./components/shell/FreshnessBanner";
import Sidebar from "./components/shell/Sidebar";
import Topbar from "./components/shell/Topbar";
import { setInert, useDrawer } from "./hooks/useDrawer";
import { useDocumentTitle } from "./hooks/useDocumentTitle";
import { isAppRoute } from "./shell/crumbs";
import { ShellOverrideProvider, useShellDeadEnd } from "./shell/shellOverride";
import { useShellContext } from "./shell/useShellContext";
import { useShellCrumbs } from "./shell/useShellCrumbs";
import { useAppStatusPoll } from "./shell/useShellData";
import { useHomeRevalidation, usePaletteHotkey, useRouteAnnouncer } from "./shell/useShellEffects";

function Shell() {
  const ctx = useShellContext();
  const location = useLocation();
  const client = useQueryClient();
  const drawer = useDrawer();
  const [paletteOpen, setPaletteOpen] = useState(false);
  const shellRef = useRef<HTMLDivElement>(null);

  const { crumbs, cli, title, subject } = useShellCrumbs(ctx);
  useDocumentTitle(title);
  const announced = useRouteAnnouncer(title, subject, ctx.override ?? ctx.routeId, useShellDeadEnd());
  usePaletteHotkey(setPaletteOpen);
  useHomeRevalidation();
  const status = useAppStatusPoll(ctx.ws, ctx.appTag);
  // A layout effect: the shell must be focusable again before the closing
  // palette hands focus back to its opener.
  useLayoutEffect(() => setInert(shellRef.current, paletteOpen), [paletteOpen]);

  const onNavigate = drawer.narrow ? drawer.close : undefined;
  // The one selection tray, under every page of an app.
  const trayApp = isAppRoute(ctx.routeId) ? { ws: ctx.params.ws, app: ctx.appTag } : {};
  return (
    <>
      <a className="skip-link" href="#main">Skip to content</a>
      <div className="shell" ref={shellRef}>
        <aside className="sidebar" id="sidebar" ref={drawer.sidebarRef} data-open={drawer.open || undefined}>
          <div className="drawer-context"><ContextRoot ctx={ctx} /></div>
          <Sidebar ctx={ctx} onNavigate={onNavigate} footExtra={<div className="drawer-theme"><ThemeToggle /></div>} />
        </aside>
        {drawer.open && <div className="drawer-veil" aria-hidden="true" onClick={drawer.close} />}
        <div className="main-col" ref={drawer.mainRef}>
          <header className="topbar">
            <Topbar
              ctx={ctx}
              crumbs={<Crumbs root={<ContextRoot ctx={ctx} />} crumbs={crumbs} cli={cli} />}
              onSearch={() => setPaletteOpen(true)}
              onMenu={drawer.narrow ? drawer.toggle : undefined}
              menuOpen={drawer.open}
              onSignOut={() => void signOut(client, ctx.meta)}
            />
          </header>
          <main id="main" className="content" tabIndex={-1}>
            <div className={`content-inner${ctx.wide ? " wide" : ""}`}>
              <AuthGate>
                <FreshnessBanner freshness={isAppRoute(ctx.routeId) ? status?.freshness : undefined} />
                <SelectionTrayHost {...trayApp}>
                  {/* Pages stay mounted across param changes (their caches paint
                      at once); only a render error is reset by navigating. */}
                  <ErrorBoundary resetKey={location.pathname}>
                    <Outlet />
                  </ErrorBoundary>
                </SelectionTrayHost>
              </AuthGate>
            </div>
          </main>
        </div>
      </div>
      {paletteOpen && <CommandPalette ctx={ctx} onClose={() => setPaletteOpen(false)} />}
      <div className="sr-only shell-announce" aria-live="polite">{announced}</div>
    </>
  );
}

export default function App() {
  return (
    <ShellOverrideProvider>
      <Shell />
    </ShellOverrideProvider>
  );
}
