import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, appTag } from "../api";
import type { AppRow, Workspace } from "../types";
import { PageHead, Skeleton } from "../components/ui";

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
    <div className="card">
      <div className="eyebrow">add a workspace</div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "130px 1.4fr 1.2fr auto",
          gap: 12,
          alignItems: "end",
        }}
      >
        <label className="field">
          name
          <input placeholder="my-repo" value={name}
            onChange={(e) => setName(e.target.value)} />
        </label>
        <label className="field">
          remote
          <input className="mono" placeholder="git@host:org/repo.git (optional)"
            value={remote}
            onChange={(e) => setRemote(e.target.value)} />
        </label>
        <label className="field">
          path
          <input className="mono"
            placeholder={cloning ? "(managed dir)" : "/abs/path/to/checkout"}
            value={path}
            onChange={(e) => setPath(e.target.value)} />
        </label>
        <button className="primary" onClick={submit} disabled={busy || !ready}>
          {busy ? (cloning ? "Cloning…" : "Attaching…") : cloning ? "Clone" : "Attach"}
        </button>
      </div>
      <p className="page-sub" style={{ margin: "12px 0 0", fontSize: 12.5 }}>
        {cloning
          ? "Clones the remote on the server host — into the managed workspaces dir, or the given path."
          : "Attaches an existing local checkout — a path on the server host with a .git or .vmn directory. Fill remote to clone instead."}
      </p>
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
      <PageHead title="Workspaces" mono={false} />
      <p className="page-sub">
        Each workspace is an isolated checkout — its own working tree,
        experiments, and lock.
      </p>
      <AddWorkspace onAdded={load} />
      {workspaces === null ? (
        <Skeleton />
      ) : workspaces.length === 0 ? (
        <div className="empty">
          No workspaces yet. Attach one above, or start the server inside a vmn repo.
        </div>
      ) : (
        <div className="grid">
          {workspaces.map((w) => (
            <Link key={w.name} to={`/ws/${w.name}`}>
              <div className="card tile">
                <div className="head">
                  <span className="status-dot" />
                  <span className="name">{w.name}</span>
                </div>
                <div className="meta mono">
                  {w.kind === "s3" ? `s3://${w.bucket}` : w.path}
                </div>
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
  if (apps === null) return <Skeleton />;
  if (apps.length === 0)
    return <div className="empty">No vmn apps in this workspace yet.</div>;

  return (
    <>
      <PageHead title={ws} mono={false} />
      <p className="page-sub">
        {apps.length} app{apps.length === 1 ? "" : "s"} in this workspace
      </p>
      <div className="grid">
        {apps.map((a) => (
          <Link key={a.name} to={`/ws/${ws}/app/${appTag(a.name)}`}>
            <div className="card tile">
              <div className="head">
                <span className="status-dot" />
                <span className="name">{a.name}</span>
              </div>
              <div className="meta">
                <span>{a.experiments} experiment{a.experiments === 1 ? "" : "s"}</span>
                <span>{a.versions} version{a.versions === 1 ? "" : "s"}</span>
              </div>
            </div>
          </Link>
        ))}
      </div>
    </>
  );
}
