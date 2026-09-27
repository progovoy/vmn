import { useState } from "react";
import type { EnvData, InputEntry } from "../types";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function _pythonVersion(python: EnvData["python"]): string {
  if (!python) return "";
  if (typeof python === "string") return python;
  return python.version ?? "";
}

function _platformStr(platform: EnvData["platform"]): string {
  if (!platform) return "";
  if (typeof platform === "string") return platform;
  return [platform.system, platform.machine].filter(Boolean).join("/");
}

function _shortDigest(digest: string | null | undefined): string {
  if (!digest) return "—";
  // Strip prefix (e.g. "sha256:") and show first 12 chars of the hash.
  const bare = digest.includes(":") ? digest.split(":").slice(1).join(":") : digest;
  return bare.length > 12 ? bare.slice(0, 12) + "…" : bare;
}

function _isMLflow(importedFrom: string | null | undefined): boolean {
  return typeof importedFrom === "string" && importedFrom.startsWith("mlflow:");
}

// ---------------------------------------------------------------------------
// EnvCard
// ---------------------------------------------------------------------------

/** Python/platform summary + optional filterable package table. */
export function EnvCard({ env }: { env: EnvData }) {
  const [filter, setFilter] = useState("");
  const pyVersion = _pythonVersion(env.python);
  const platformStr = _platformStr(env.platform);
  const packages = env.packages;
  const hasPackageTable = packages != null && Object.keys(packages).length > 0;
  const filtered = hasPackageTable
    ? Object.entries(packages).filter(
        ([name]) => !filter || name.toLowerCase().includes(filter.toLowerCase()),
      )
    : [];

  return (
    <div className="card">
      <div className="eyebrow">environment</div>
      {env.truncated && (
        <div className="env-truncated" style={{ fontSize: 12, color: "var(--muted)", marginBottom: 6 }}>
          Package list truncated (env.yml exceeded size cap)
        </div>
      )}
      <div className="kv">
        {pyVersion && <><div className="k">python</div><div className="mono">{pyVersion}</div></>}
        {platformStr && <><div className="k">platform</div><div className="mono">{platformStr}</div></>}
        {env.packages_count != null && !hasPackageTable && (
          <><div className="k">packages</div><div>{env.packages_count} installed</div></>
        )}
        {env.cuda && (
          <>
            <div className="k">cuda</div>
            <div className="mono">{Object.entries(env.cuda).map(([k, v]) => `${k}: ${v}`).join(", ")}</div>
          </>
        )}
      </div>
      {hasPackageTable && (
        <>
          <input
            className="filter-input"
            placeholder="filter packages…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            style={{ marginTop: 8, marginBottom: 6, padding: "2px 6px", width: "100%", boxSizing: "border-box" }}
          />
          <table className="env-packages" style={{ fontSize: 12, width: "100%", borderCollapse: "collapse" }}>
            <tbody>
              {filtered.map(([name, version]) => (
                <tr key={name}>
                  <td className="mono" style={{ paddingRight: 12 }}>{name}</td>
                  <td className="mono" style={{ color: "var(--muted)" }}>{version}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// InputsCard
// ---------------------------------------------------------------------------

/** Logged dataset / artefact inputs. */
export function InputsCard({ inputs }: { inputs: Record<string, InputEntry> }) {
  const entries = Object.entries(inputs);
  if (entries.length === 0) return null;
  return (
    <div className="card">
      <div className="eyebrow">inputs</div>
      <table className="inputs-table" style={{ fontSize: 12, width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr>
            <th style={{ textAlign: "left", fontWeight: 600, paddingRight: 12 }}>name</th>
            <th style={{ textAlign: "left", fontWeight: 600, paddingRight: 12 }}>uri</th>
            <th style={{ textAlign: "left", fontWeight: 600, paddingRight: 12 }}>digest</th>
            <th style={{ textAlign: "left", fontWeight: 600 }}>kind</th>
          </tr>
        </thead>
        <tbody>
          {entries.map(([name, entry]) => (
            <tr key={name}>
              <td className="mono" style={{ paddingRight: 12 }}>{name}</td>
              <td className="mono" style={{ paddingRight: 12, wordBreak: "break-all" }}>{entry.uri}</td>
              <td className="mono" style={{ paddingRight: 12 }} title={entry.digest ?? ""}>{_shortDigest(entry.digest)}</td>
              <td style={{ color: "var(--muted)" }}>{entry.kind ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// ImportedBadge
// ---------------------------------------------------------------------------

/** A badge shown when a run was imported from an external system (e.g. MLflow). */
export function ImportedBadge({ importedFrom }: { importedFrom: string | null | undefined }) {
  if (!importedFrom) return null;
  const label = _isMLflow(importedFrom) ? "Imported from MLflow" : `Imported from ${importedFrom}`;
  return (
    <span className="badge badge-imported" style={{ marginRight: 8 }}>{label}</span>
  );
}

// ---------------------------------------------------------------------------
// RunProvenanceSection — rendered on the Run page when data is present
// ---------------------------------------------------------------------------

export default function RunProvenanceSection({
  env,
  inputs,
  importedFrom,
}: {
  env?: EnvData | null;
  inputs?: Record<string, InputEntry> | null;
  importedFrom?: string | null;
}) {
  const hasEnv = env != null;
  const hasInputs = inputs != null && Object.keys(inputs).length > 0;
  if (!hasEnv && !hasInputs && !importedFrom) return null;
  return (
    <div className="run-provenance">
      {importedFrom && <ImportedBadge importedFrom={importedFrom} />}
      {hasInputs && <InputsCard inputs={inputs!} />}
      {hasEnv && <EnvCard env={env!} />}
    </div>
  );
}
