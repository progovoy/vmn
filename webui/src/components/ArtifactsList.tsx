import { useState, type MouseEvent } from "react";
import { authHeaders } from "../http";

function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** Fetch with the Authorization header and hand the blob to the browser.
 *  A plain `<a download>` can't send the header, so with a token set it would
 *  always get a 401. */
async function downloadWithToken(url: string, name: string, headers: Record<string, string>) {
  const res = await fetch(url, { headers });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const href = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = href;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(href);
}

export default function ArtifactsList({ artifacts, downloadUrl }: {
  artifacts: { name: string; size: number }[];
  downloadUrl: (filename: string) => string;
}) {
  const [error, setError] = useState<string | null>(null);
  if (artifacts.length === 0) return null;

  const onClick = (e: MouseEvent<HTMLAnchorElement>, name: string) => {
    const headers = authHeaders();
    if (!headers.Authorization) return; // no auth: the plain link works as is
    e.preventDefault();
    setError(null);
    downloadWithToken(downloadUrl(name), name, headers).catch((err) =>
      setError(`${name}: ${String((err as Error).message ?? err)}`)
    );
  };

  return (
    <div className="card">
      <div className="eyebrow">artifacts</div>
      {error && <div className="error">{error}</div>}
      <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
        {artifacts.map((a) => (
          <li
            key={a.name}
            style={{
              display: "flex", justifyContent: "space-between", alignItems: "center",
              padding: "6px 0", borderBottom: "1px solid var(--line)",
            }}
          >
            <a
              href={downloadUrl(a.name)}
              download
              onClick={(e) => onClick(e, a.name)}
              style={{ color: "var(--accent)" }}
            >
              {a.name}
            </a>
            <span style={{ color: "var(--text-3)", fontSize: 12 }}>{fmtSize(a.size)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
