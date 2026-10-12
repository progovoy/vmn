/** Attach a checkout on the server host, or clone a remote into one. */
import { useState, type FormEvent } from "react";
import { api } from "../api";
import "../pages/home.css";

export default function AddWorkspace({ onAdded, initialName = "" }: {
  onAdded: () => void; initialName?: string;
}) {
  const [name, setName] = useState(initialName);
  const [remote, setRemote] = useState("");
  const [path, setPath] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const cloning = remote.trim() !== "";
  const ready = name.trim() && (cloning || path.trim());

  const submit = async (e: FormEvent) => {
    e.preventDefault();
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
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="add-ws-form" onSubmit={submit}>
      <div className="add-ws-fields">
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
        <button type="submit" className="primary" disabled={busy || !ready}>
          {busy ? (cloning ? "Cloning…" : "Attaching…") : cloning ? "Clone" : "Attach"}
        </button>
      </div>
      <p className="add-ws-help">
        {cloning
          ? "Clones the remote on the server host, into the managed workspaces dir or the given path."
          : "Attaches an existing checkout: a path on the server host with a .git or .vmn directory. Fill remote to clone instead."}
      </p>
      {error && <div className="error" role="alert">{error}</div>}
    </form>
  );
}
