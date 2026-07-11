import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, appTag } from "../api";
import type { AppRow, Workspace } from "../types";

function AddWorkspace({ onAdded }: { onAdded: () => void }) {
  const [name, setName] = useState("");
  const [remote, setRemote] = useState("");
  const [path, setPath] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const cloning = remote.trim() !== "";
  const ready = name.trim() && (cloning || path.trim());

  const submit = async () => {
    if (!ready) return;
    setBusy(true);
    setError(null);
    try {
      await api.addWorkspace(name.trim(), {
        remote: remote.trim() || undefined,
        path: path.trim() || undefined,
      });
      setName("");
      setRemote("");
      setPath("");
      onAdded();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <h2 style={{ marginTop: 0 }}>add a workspace</h2>
      <div className="toolbar" style={{ flexWrap: "wrap" }}>
        <label>
          name{" "}
          <input placeholder="my-repo" value={name}
            onChange={(e) => setName(e.target.value)} style={{ width: 130 }} />
        </label>
        <label>
          remote{" "}
          <input className="mono" placeholder="git@host:org/repo.git (optional)"
            value={remote}
            onChange={(e) => setRemote(e.target.value)} style={{ width: 250 }} />
        </label>
        <label>
          path{" "}
          <input className="mono"
            placeholder={cloning ? "(managed dir)" : "/abs/path/to/checkout"}
            value={path}
            onChange={(e) => setPath(e.target.value)} style={{ width: 220 }} />
        </label>
        <button className="primary" onClick={submit} disabled={busy || !ready}>
          {busy ? (cloning ? "Cloning…" : "Attaching…") : cloning ? "Clone" : "Attach"}
        </button>
      </div>
      <div className="cli-hint">
        {cloning
          ? "Clones the remote on the server host — into the managed workspaces dir, or the given path."
          : "Attaches an existing local checkout — a path on the server host with a .git or .vmn directory. Fill remote to clone instead."}
      </div>
      {error && <div className="error" style={{ marginTop: 8 }}>{error}</div>}
    </div>
  );
}

export function WorkspacesHome() {
  const [workspaces, setWorkspaces] = useState<Workspace[] | null>(null);

  const load = () =>
    api.workspaces().then(setWorkspaces).catch(() => setWorkspaces([]));
  useEffect(() => { load(); }, []);

  return (
    <>
      <h1>Workspaces</h1>
      <p className="subtitle">
        Each workspace is an isolated checkout — its own working tree,
        experiments, and lock.
      </p>
      <AddWorkspace onAdded={load} />
      {workspaces === null ? (
        <div className="empty">Loading…</div>
      ) : workspaces.length === 0 ? (
        <div className="empty">
          No workspaces yet. Attach one above, or start the server inside a vmn repo.
        </div>
      ) : (
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
      )}
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
