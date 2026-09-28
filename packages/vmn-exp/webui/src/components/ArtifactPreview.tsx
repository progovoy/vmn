import { useEffect, useState } from "react";
import { authHeaders } from "../http";
import {
  artifactKind, extensionOf, parseDelimited, TABLE_PREVIEW_ROWS, TEXT_PREVIEW_BYTES, truncateText,
} from "../util/artifactKinds";
import type { Artifact } from "../util/artifactTree";

type Loaded<T> = { data?: T; error?: string };

/** Fetch once on mount (the preview only mounts when asked for). */
function useFetched<T>(url: string, read: (res: Response) => Promise<T>, init?: RequestInit, skip = false) {
  const [state, setState] = useState<Loaded<T>>({});
  useEffect(() => {
    if (skip) return;
    let live = true;
    fetch(url, init)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return read(res);
      })
      .then((data) => live && setState({ data }), (e) => live && setState({ error: String(e.message ?? e) }));
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, skip]);
  return state;
}

const rangeInit = (): RequestInit => ({
  headers: authHeaders({ Range: `bytes=0-${TEXT_PREVIEW_BYTES - 1}` }),
});

function Status({ state }: { state: Loaded<unknown> }) {
  if (state.error) return <div className="error">preview failed: {state.error}</div>;
  return <div className="artifact-loading">loading preview…</div>;
}

function ImagePreview({ url, name }: { url: string; name: string }) {
  // A plain <img> can't send the Authorization header: with a token, fetch
  // the bytes ourselves and show them from a blob URL.
  const headers = authHeaders();
  const tokened = Boolean(headers.Authorization);
  const blob = useFetched(url, (r) => r.blob().then((b) => URL.createObjectURL(b)), { headers }, !tokened);
  useEffect(() => () => { if (blob.data) URL.revokeObjectURL(blob.data); }, [blob.data]);
  if (tokened && !blob.data) return <Status state={blob} />;
  return <img className="artifact-img" src={tokened ? blob.data : url} alt={name} />;
}

function TablePreview({ url, name }: { url: string; name: string }) {
  const delim = extensionOf(name) === "tsv" ? "\t" : ",";
  const state = useFetched(url, (r) => r.text(), rangeInit());
  if (state.data === undefined) return <Status state={state} />;
  const rows = parseDelimited(truncateText(state.data).text, delim, TABLE_PREVIEW_ROWS + 2);
  const [head = [], ...body] = rows;
  const shown = body.slice(0, TABLE_PREVIEW_ROWS);
  return (
    <div className="artifact-table">
      <table>
        <thead><tr>{head.map((h, i) => <th key={i}>{h}</th>)}</tr></thead>
        <tbody>
          {shown.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j}>{c}</td>)}</tr>)}
        </tbody>
      </table>
      {body.length > TABLE_PREVIEW_ROWS && (
        <div className="artifact-note">showing the first {TABLE_PREVIEW_ROWS} rows</div>
      )}
    </div>
  );
}

function TextPreview({ url, size }: { url: string; size: number }) {
  const state = useFetched(url, (r) => r.text(), rangeInit());
  if (state.data === undefined) return <Status state={state} />;
  const { text, truncated } = truncateText(state.data);
  return (
    <>
      <pre className="artifact-text">{text}</pre>
      {(truncated || size > TEXT_PREVIEW_BYTES) && (
        <div className="artifact-note">truncated — showing the first {TEXT_PREVIEW_BYTES / 1024} KB</div>
      )}
    </>
  );
}

/** An artifact's contents, inline: images as images, CSV/TSV as a table,
 *  text-like files as text — each bounded so a huge file stays cheap. */
export default function ArtifactPreview({ artifact, url }: { artifact: Artifact; url: string }) {
  const kind = artifactKind(artifact.name);
  return (
    <div className="artifact-preview">
      {kind === "image" && <ImagePreview url={url} name={artifact.name} />}
      {kind === "table" && <TablePreview url={url} name={artifact.name} />}
      {kind === "text" && <TextPreview url={url} size={artifact.size} />}
    </div>
  );
}
