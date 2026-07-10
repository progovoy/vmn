import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, appTag } from "../api";
import type { AppRow, Workspace } from "../types";

export function WorkspacesHome() {
  const [workspaces, setWorkspaces] = useState<Workspace[] | null>(null);

  useEffect(() => {
    api.workspaces().then(setWorkspaces).catch(() => setWorkspaces([]));
  }, []);

  if (workspaces === null) return <div className="empty">Loading…</div>;
  if (workspaces.length === 0)
    return (
      <div className="empty">
        No workspaces yet. Start the server inside a vmn repo, or attach one
        via the API.
      </div>
    );

  return (
    <>
      <h1>Workspaces</h1>
      <p className="subtitle">
        Each workspace is an isolated checkout — its own working tree,
        experiments, and lock.
      </p>
      <div className="grid">
        {workspaces.map((w) => (
          <Link key={w.name} to={`/ws/${w.name}`}>
            <div className="card tile">
              <div className="name">{w.name}</div>
              <div className="meta mono">{w.kind === "s3" ? `s3://${w.bucket}` : w.path}</div>
            </div>
          </Link>
        ))}
      </div>
    </>
  );
}

export function AppsPage() {
  const { ws } = useParams() as { ws: string };
  const [apps, setApps] = useState<AppRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.apps(ws).then(setApps).catch((e) => setError(String(e)));
  }, [ws]);

  if (error) return <div className="error">{error}</div>;
  if (apps === null) return <div className="empty">Loading…</div>;
  if (apps.length === 0)
    return <div className="empty">No vmn apps in this workspace yet.</div>;

  return (
    <>
      <h1>{ws}</h1>
      <p className="subtitle">{apps.length} app(s)</p>
      <div className="grid">
        {apps.map((a) => (
          <Link key={a.name} to={`/ws/${ws}/app/${appTag(a.name)}`}>
            <div className="card tile">
              <div className="name">{a.name}</div>
              <div className="meta">{a.experiments} experiment(s)</div>
            </div>
          </Link>
        ))}
      </div>
    </>
  );
}
