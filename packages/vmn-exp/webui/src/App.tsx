/** The dashboard shell (plan 19 §1.1): skip link, the sidebar (a drawer below
 *  900px), the topbar with crumbs, the page outlet behind the sign-in gate,
 *  ⌘K, and a live region that reads each new page's title. */
import { useQueryClient } from "@tanstack/react-query";
import { useLayoutEffect, useRef, useState } from "react";
import { Outlet, useLocation, useMatches } from "react-router-dom";
import AuthGate from "./auth/AuthGate";
import { signOut } from "./auth/authState";
import CommandPalette from "./components/CommandPalette";
import ErrorBoundary from "./components/ErrorBoundary";
import ThemeToggle from "./components/ThemeToggle";
import ContextRoot from "./components/shell/ContextRoot";
import Crumbs from "./components/shell/Crumbs";
import Sidebar from "./components/shell/Sidebar";
import Topbar from "./components/shell/Topbar";
import { setInert, useDrawer } from "./hooks/useDrawer";
import { useDocumentTitle } from "./hooks/useDocumentTitle";
import type { RouteHandle } from "./shell/contracts";
import { ShellOverrideProvider } from "./shell/shellOverride";
import { useShellContext } from "./shell/useShellContext";
import { useShellCrumbs } from "./shell/useShellCrumbs";
import { useAppStatusPoll } from "./shell/useShellData";
import { useHomeRevalidation, usePaletteHotkey, useRouteAnnouncer } from "./shell/useShellEffects";

/** Whether the deepest route asks for the full content width. */
function useWide(): boolean {
  const matches = useMatches();
  return Boolean((matches[matches.length - 1]?.handle as RouteHandle | undefined)?.wide);
}

function Shell() {
  const ctx = useShellContext();
  const location = useLocation();
  const client = useQueryClient();
  const drawer = useDrawer();
  const wide = useWide();
  const [paletteOpen, setPaletteOpen] = useState(false);
  const shellRef = useRef<HTMLDivElement>(null);

  const { crumbs, cli, title, subject } = useShellCrumbs(ctx);
  useDocumentTitle(title);
  const announced = useRouteAnnouncer(title, subject, ctx.override ?? ctx.routeId);
  usePaletteHotkey(setPaletteOpen);
  useHomeRevalidation();
  useAppStatusPoll(ctx.ws, ctx.appTag);
  // A layout effect: the shell must be focusable again before the closing
  // palette hands focus back to its opener.
  useLayoutEffect(() => setInert(shellRef.current, paletteOpen), [paletteOpen]);

  const onNavigate = drawer.narrow ? drawer.close : undefined;
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
            <div className={`content-inner${wide ? " wide" : ""}`}>
              <AuthGate>
                {/* Pages stay mounted across param changes (their caches paint
                    at once); only a render error is reset by navigating. */}
                <ErrorBoundary resetKey={location.pathname}>
                  <Outlet />
                </ErrorBoundary>
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
