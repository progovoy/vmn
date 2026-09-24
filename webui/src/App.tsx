import { useEffect, useRef, useState } from "react";
import {
  Link, NavLink, Outlet, useLocation, useMatches, useNavigate,
} from "react-router-dom";
import { appName as toAppName } from "./api";
import { useAppQueryClient } from "./queryClient";
import { useApps, useMeta, useWorkspaces, WORKSPACES_KEY } from "./queries";
import CommandPalette from "./components/CommandPalette";
import ErrorBoundary from "./components/ErrorBoundary";
import ThemeToggle from "./components/ThemeToggle";
import { CopyPath, wsLocation } from "./components/ui";

function NavIcon({ name }: { name: string }) {
  switch (name) {
    case "exp":
      return (
        <svg width="15" height="15" viewBox="0 0 15 15" fill="none">
          <rect x="1" y="9" width="3" height="5" rx="1" fill="currentColor" />
          <rect x="6" y="5" width="3" height="9" rx="1" fill="currentColor" />
          <rect x="11" y="2" width="3" height="12" rx="1" fill="currentColor" />
        </svg>
      );
    case "snap":
      return (
        <svg width="15" height="15" viewBox="0 0 15 15" fill="none">
          <circle cx="7.5" cy="7.5" r="5.5" stroke="currentColor" strokeWidth="1.6" />
          <circle cx="7.5" cy="7.5" r="1.8" fill="currentColor" />
        </svg>
      );
    case "tree":
      return (
        <svg width="15" height="15" viewBox="0 0 15 15" fill="none">
          <path d="M3.5 2.5v6a2 2 0 0 0 2 2h6" stroke="currentColor" strokeWidth="1.6" />
          <circle cx="3.5" cy="2.5" r="1.9" fill="currentColor" />
          <circle cx="11.5" cy="10.5" r="1.9" fill="currentColor" />
        </svg>
      );
    default:
      return (
        <svg width="15" height="15" viewBox="0 0 15 15" fill="none">
          <path d="M4 2.5l8 5-8 5v-10z" fill="currentColor" />
        </svg>
      );
  }
}

export default function App() {
  const [paletteOpen, setPaletteOpen] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();

  // Route context comes from the router itself (see handle.page in main.tsx).
  const matches = useMatches();
  const deepest = matches[matches.length - 1];
  const { ws, app: appTag } = (deepest?.params ?? {}) as {
    ws?: string; app?: string;
  };
  const pageLabel = (deepest?.handle as { page?: string } | undefined)?.page;
  const appName = appTag ? toAppName(appTag) : undefined;
  const appBase = ws && appTag ? `/ws/${ws}/app/${appTag}` : null;
  const workspaces = useWorkspaces().data ?? [];
  const apps = useApps(ws).data ?? [];
  const vmnVersion = useMeta().data?.version ?? "";
  const currentWs = workspaces.find((w) => w.name === ws);

  // Revalidate on entering/leaving home — the add-workspace form lives there.
  const client = useAppQueryClient();
  const atHome = location.pathname === "/";
  const firstVisit = useRef(true);
  useEffect(() => {
    if (firstVisit.current) { firstVisit.current = false; return; }
    client.invalidateQueries({ queryKey: WORKSPACES_KEY });
  }, [atHome, client]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((o) => !o);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="shell">
      <aside className="sidebar">
        <Link to="/" className="sb-brand">
          <span className="logo">v</span>
          <span className="word">vmn<span> ui</span></span>
        </Link>

        <div className="sb-group">
          <div className="sb-label">Workspace</div>
          <div className="select-wrap">
            <select
              value={ws ?? ""}
              onChange={(e) => e.target.value && navigate(`/ws/${e.target.value}`)}
            >
              <option value="" disabled>
                workspace…
              </option>
              {workspaces.map((w) => (
                <option key={w.name} value={w.name}>
                  {w.name} {w.kind === "s3" ? "(s3)" : ""}
                </option>
              ))}
            </select>
          </div>
          {currentWs && <CopyPath text={wsLocation(currentWs)} />}
        </div>

        {appName && (
          <>
            <div className="sb-divider" />
            <div className="sb-group">
              <div className="sb-label">App</div>
              <div className="sb-app">
                <span className="status-dot" />
                <span className="name">{appName}</span>
              </div>
            </div>
          </>
        )}

        {appBase && (
          <nav className="sb-nav">
            <NavLink to={appBase} end>
              <NavIcon name="exp" /> Experiments
            </NavLink>
            <NavLink to={`${appBase}/snapshots`}>
              <NavIcon name="snap" /> Snapshots
            </NavLink>
            <NavLink to={`${appBase}/tree`}>
              <NavIcon name="tree" /> Stamp tree
            </NavLink>
            <NavLink to={`${appBase}/actions`}>
              <NavIcon name="actions" /> Actions
            </NavLink>
          </nav>
        )}

        <div className="sb-foot">
          <span className="ver">vmn {vmnVersion || "ui"}</span>
          <a href="https://github.com/progovoy/vmn" target="_blank" rel="noreferrer">
            docs ↗
          </a>
        </div>
      </aside>

      <div className="main-col">
        <header className="topbar">
          <div className="crumbs">
            {ws ? (
              <>
                <Link to={`/ws/${ws}`}>{ws}</Link>
                {appName && (
                  <>
                    <span>/</span>
                    <Link to={appBase!} className="mono">{appName}</Link>
                  </>
                )}
                <span>/</span>
                <span className="cur">{pageLabel}</span>
              </>
            ) : (
              <span className="cur">workspaces</span>
            )}
          </div>
          <div className="topbar-right">
            <button className="search-pill" onClick={() => setPaletteOpen(true)}>
              <span>Search</span>
              <span className="key">⌘K</span>
            </button>
            <ThemeToggle />
            <div className="host-chip">
              <span className="status-dot pulse" />
              <span>local</span>
            </div>
          </div>
        </header>

        <div className="content">
          <div className="content-inner">
            {/* Pages stay mounted across param changes (their caches paint
                at once); only a render error is reset by navigating. */}
            <ErrorBoundary resetKey={location.pathname}>
              <Outlet />
            </ErrorBoundary>
          </div>
        </div>
      </div>

      {paletteOpen && (
        <CommandPalette
          ws={ws}
          app={appName}
          workspaces={workspaces}
          apps={apps}
          onClose={() => setPaletteOpen(false)}
        />
      )}
    </div>
  );
}
