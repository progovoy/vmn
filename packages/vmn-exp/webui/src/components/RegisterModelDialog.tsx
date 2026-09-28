import { useState } from "react";
import { apiModels } from "../apiModels";

/** Dialog for registering a run artifact as a model version. */
export default function RegisterModelDialog({
  ws, app, verstr, onDone,
}: {
  ws: string;
  app: string;
  verstr: string;
  onDone: () => void;
}) {
  const [modelName, setModelName] = useState("");
  const [artifactPath, setArtifactPath] = useState("");
  const [alias, setAlias] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!modelName.trim()) {
      setError("Model name is required");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await apiModels.registerVersion(ws, modelName.trim(), {
        run: { app, verstr },
        artifact_path: artifactPath.trim() || undefined,
        alias: alias.trim() || undefined,
        description: description.trim() || undefined,
      });
      onDone();
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="modal-backdrop"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onDone(); }}
    >
      <div
        className="card confirm-dialog"
        role="dialog"
        aria-modal="true"
        aria-label="Register as model"
        onKeyDown={(e) => { if (e.key === "Escape") { e.stopPropagation(); onDone(); } }}
        style={{ minWidth: 320 }}
      >
        <div className="eyebrow">register as model</div>
        <div style={{ display: "flex", flexDirection: "column", gap: 10, margin: "12px 0" }}>
          <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            Model name
            <input
              aria-label="Model name"
              value={modelName}
              onChange={(e) => setModelName(e.target.value)}
              placeholder="e.g. fraud-detector"
              autoFocus
            />
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            Artifact path (optional)
            <input
              aria-label="Artifact path"
              value={artifactPath}
              onChange={(e) => setArtifactPath(e.target.value)}
              placeholder="e.g. model.pkl"
            />
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            Alias (optional)
            <input
              aria-label="Alias"
              value={alias}
              onChange={(e) => setAlias(e.target.value)}
              placeholder="e.g. production"
            />
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            Description (optional)
            <input
              aria-label="Description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </label>
        </div>
        {error && <div className="error">{error}</div>}
        <div className="confirm-actions">
          <button onClick={onDone}>Cancel</button>
          <button className="primary" onClick={submit} disabled={busy}>
            Register
          </button>
        </div>
      </div>
    </div>
  );
}
