import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { appTag } from "../api";
import { apiModels } from "../apiModels";
import type { ModelVersion, AuditEntry } from "../apiModels";
import { relTime } from "../util";
import { PageHead, Skeleton } from "../components/ui";

// ---------------------------------------------------------------------------
// Alias move dialog
// ---------------------------------------------------------------------------

interface AliasDialogProps {
  ws: string;
  modelName: string;
  alias: string;
  currentVersion: number;
  onDone: () => void;
}

function AliasMoveDialog({ ws, modelName, alias, currentVersion, onDone }: AliasDialogProps) {
  const [newVersion, setNewVersion] = useState(currentVersion);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const client = useQueryClient();

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await apiModels.moveAlias(ws, modelName, alias, newVersion, currentVersion);
      client.invalidateQueries({ queryKey: ["model", ws, modelName] });
      onDone();
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onDone(); }}>
      <div className="card confirm-dialog" role="dialog" aria-modal="true">
        <p>Move alias <strong>{alias}</strong> to version:</p>
        <label>
          Version
          <input
            type="number"
            min={1}
            value={newVersion}
            onChange={(e) => setNewVersion(Number(e.target.value))}
            aria-label="Version"
          />
        </label>
        {error && <div className="error">{error}</div>}
        <div className="confirm-actions">
          <button onClick={onDone}>Cancel</button>
          <button className="primary" onClick={submit} disabled={busy} autoFocus>
            Confirm
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Version row
// ---------------------------------------------------------------------------

function VersionRow({
  version, ws, onMoveAlias,
}: {
  version: ModelVersion;
  ws: string;
  onMoveAlias: (alias: string, currentVersion: number) => void;
}) {
  const runHref =
    `/ws/${ws}/app/${appTag(version.run.app)}/run/${encodeURIComponent(version.run.verstr)}`;

  return (
    <tr>
      <td className="mono">v{version.version}</td>
      <td>
        <span className={`badge status-${version.status}`}>{version.status}</span>
      </td>
      <td>
        <Link className="mono" to={runHref}>{version.run.verstr}</Link>
        <span style={{ color: "var(--text-3)", fontSize: 12, marginLeft: 4 }}>
          {version.run.app}
        </span>
      </td>
      <td className="mono">{version.artifact_path ?? "—"}</td>
      <td>
        {version.aliases.map((alias) => (
          <span key={alias} className="tag-chip">
            <span>{alias}</span>
            <button
              className="link"
              style={{ marginLeft: 4, fontSize: 11 }}
              aria-label={`move ${alias}`}
              onClick={() => onMoveAlias(alias, version.version)}
            >
              move
            </button>
          </span>
        ))}
      </td>
      <td title={version.created ?? ""}>{version.created ? relTime(version.created) : "—"}</td>
    </tr>
  );
}

// ---------------------------------------------------------------------------
// Audit log
// ---------------------------------------------------------------------------

function AuditLog({ entries }: { entries: AuditEntry[] }) {
  return (
    <div className="card">
      <div className="eyebrow">audit</div>
      {entries.length === 0 ? (
        <div className="empty">No audit entries.</div>
      ) : (
        <table style={{ width: "100%" }}>
          <thead>
            <tr>
              <th>time</th>
              <th>actor</th>
              <th>event</th>
              <th>alias</th>
              <th>version</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((e) => (
              <tr key={`${e.ts}-${e.actor}-${e.type}`}>
                <td title={e.ts}>{relTime(e.ts)}</td>
                <td className="mono">{e.actor}</td>
                <td>{e.type}</td>
                <td className="mono">{e.alias != null ? `@${e.alias}` : "—"}</td>
                <td className="mono">{e.version != null ? e.version : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function ModelDetailPage() {
  const { ws, modelName } = useParams() as { ws: string; modelName: string };
  const client = useQueryClient();
  const query = useQuery(
    {
      queryKey: ["model", ws, modelName],
      queryFn: () => apiModels.getModel(ws, modelName),
    },
    client,
  );

  const [moving, setMoving] = useState<{ alias: string; currentVersion: number } | null>(null);

  if (query.error && !query.data) {
    return <div className="error">{String(query.error)}</div>;
  }
  if (!query.data) return <Skeleton />;

  const { versions, audit } = query.data;

  return (
    <>
      <Link className="back-link" to={`/ws/${ws}/models`}>← models</Link>
      <PageHead title={modelName} what="model" mono />
      {query.data.description && (
        <p style={{ color: "var(--text-2)", marginBottom: 16 }}>{query.data.description}</p>
      )}

      <div className="card" style={{ padding: 0, overflow: "auto", marginBottom: 16 }}>
        <div className="eyebrow" style={{ padding: "10px 16px" }}>versions</div>
        <table style={{ width: "100%" }}>
          <thead>
            <tr>
              <th>version</th>
              <th>status</th>
              <th>run</th>
              <th>artifact</th>
              <th>aliases</th>
              <th>created</th>
            </tr>
          </thead>
          <tbody>
            {versions.map((v) => (
              <VersionRow
                key={v.version}
                version={v}
                ws={ws}
                onMoveAlias={(alias, currentVersion) => setMoving({ alias, currentVersion })}
              />
            ))}
          </tbody>
        </table>
      </div>

      <AuditLog entries={audit} />

      {moving && (
        <AliasMoveDialog
          ws={ws}
          modelName={modelName}
          alias={moving.alias}
          currentVersion={moving.currentVersion}
          onDone={() => setMoving(null)}
        />
      )}
    </>
  );
}
