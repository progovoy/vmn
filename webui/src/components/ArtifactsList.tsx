import { useMemo, useState, type MouseEvent } from "react";
import { authHeaders } from "../http";
import { artifactKind } from "../util/artifactKinds";
import { buildArtifactTree, type Artifact, type ArtifactNode } from "../util/artifactTree";
import ArtifactPreview from "./ArtifactPreview";

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

interface TreeProps {
  downloadUrl: (filename: string) => string;
  onDownload: (e: MouseEvent<HTMLAnchorElement>, name: string) => void;
}

function FileRow({ artifact, label, downloadUrl, onDownload }: TreeProps & { artifact: Artifact; label: string }) {
  const [previewing, setPreviewing] = useState(false);
  const url = downloadUrl(artifact.name);
  const previewable = artifactKind(artifact.name) !== "binary";
  return (
    <li className="artifact-file">
      <div className="artifact-row">
        <a href={url} download onClick={(e) => onDownload(e, artifact.name)} title={artifact.name}>
          {label}
        </a>
        <span className="artifact-actions">
          {previewable && (
            <button className="link" aria-pressed={previewing} onClick={() => setPreviewing((v) => !v)}>
              {previewing ? "hide preview" : "preview"}
            </button>
          )}
          <span className="artifact-size">{fmtSize(artifact.size)}</span>
        </span>
      </div>
      {previewing && <ArtifactPreview artifact={artifact} url={url} />}
    </li>
  );
}

function DirRow({ node, ...props }: TreeProps & { node: Extract<ArtifactNode, { kind: "dir" }> }) {
  const [open, setOpen] = useState(true);
  return (
    <li className="artifact-dir">
      <button className="link artifact-folder" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        {open ? "▾" : "▸"} {node.label}/
      </button>
      {open && <Tree nodes={node.children} {...props} />}
    </li>
  );
}

function Tree({ nodes, ...props }: TreeProps & { nodes: ArtifactNode[] }) {
  return (
    <ul className="artifact-tree">
      {nodes.map((n) =>
        n.kind === "dir"
          ? <DirRow key={`d:${n.path}`} node={n} {...props} />
          : <FileRow key={n.artifact.name} artifact={n.artifact} label={n.label} {...props} />,
      )}
    </ul>
  );
}

export default function ArtifactsList({ artifacts, downloadUrl }: {
  artifacts: Artifact[];
  downloadUrl: (filename: string) => string;
}) {
  const [error, setError] = useState<string | null>(null);
  const tree = useMemo(() => buildArtifactTree(artifacts), [artifacts]);
  if (artifacts.length === 0) return null;

  const onDownload = (e: MouseEvent<HTMLAnchorElement>, name: string) => {
    const headers = authHeaders();
    if (!headers.Authorization) return; // no auth: the plain link works as is
    e.preventDefault();
    setError(null);
    downloadWithToken(downloadUrl(name), name.split("/").pop() ?? name, headers).catch((err) =>
      setError(`${name}: ${String((err as Error).message ?? err)}`)
    );
  };

  return (
    <div className="card">
      <div className="eyebrow">artifacts</div>
      {error && <div className="error">{error}</div>}
      <Tree nodes={tree} downloadUrl={downloadUrl} onDownload={onDownload} />
    </div>
  );
}
