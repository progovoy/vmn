import { memo, useEffect, useState } from "react";
import { copyText } from "../../util";
import { ChangelogSection } from "./ChangelogSection";
import type { Edge, Node } from "./layout";

function fmtDate(ts: number | null | undefined): string {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleString(undefined, {
    year: "numeric", month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

export const VersionDetails = memo(function VersionDetails({
  ws, app, node, canonical, edges, olderVerstrs, onSelect,
}: {
  ws: string;
  app: string;
  node: Node;
  canonical: Map<string, string>;
  edges: Edge[];
  olderVerstrs: string[];
  onSelect: (verstr: string) => void;
}) {
  const [copied, setCopied] = useState<"copied" | "no clipboard" | null>(null);
  useEffect(() => setCopied(null), [node.verstr]);

  const prev = node.row.previous_version;
  const next = edges.filter(([from]) => from === node.verstr).map(([, to]) => to);
  const deps = Object.entries(node.row.changesets ?? {}).filter(([p]) => p !== ".");

  const versionLink = (v: string) =>
    canonical.has(v) ? (
      <a key={v} onClick={() => onSelect(v)} style={{ cursor: "pointer", marginRight: 10 }} className="mono">
        {v}
      </a>
    ) : (
      <span key={v} className="mono" style={{ marginRight: 10 }}>{v}</span>
    );

  return (
    <>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <span className="mono" style={{ fontSize: 17, fontWeight: 600 }}>{node.verstr}</span>
        <span className={`badge mode mode-${node.mode}`}>{node.mode}</span>
        {node.prerelease && <span className="badge">pre: {node.prerelease}</span>}
      </div>
      <div className="kv" style={{ gridTemplateColumns: "84px 1fr", marginTop: 14 }}>
        <div className="k">stamped</div>
        <div title={fmtDate(node.row.timestamp)}>
          {node.rel}
          <span style={{ color: "var(--text-muted)" }}> · {fmtDate(node.row.timestamp)}</span>
        </div>
        <div className="k">branch</div>
        <div className="mono">{node.branch}</div>
        <div className="k">tag</div>
        <div className="mono">{node.row.tag}</div>
        {node.aliases.length > 0 && (
          <>
            <div className="k">also</div>
            <div>
              {node.aliases.map((v) => (
                <div key={v} className="mono">{v}</div>
              ))}
            </div>
          </>
        )}
        <div className="k">commit</div>
        <div className="mono" style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {node.row.commit ? (
            <>
              <span title={node.row.commit}>{node.row.commit.slice(0, 7)}</span>
              <button
                style={{ padding: "0 8px", fontSize: 11 }}
                onClick={() =>
                  copyText(node.row.commit!).then((ok) =>
                    setCopied(ok ? "copied" : "no clipboard")
                  )
                }
              >
                {copied ?? "copy"}
              </button>
            </>
          ) : "—"}
        </div>
        {prev && prev !== node.verstr && (
          <>
            <div className="k">previous</div>
            <div>{versionLink(prev)}</div>
          </>
        )}
        {next.length > 0 && (
          <>
            <div className="k">next</div>
            <div>{next.map(versionLink)}</div>
          </>
        )}
        {deps.length > 0 && (
          <>
            <div className="k">deps</div>
            <div>
              {deps.map(([path, info]) => (
                <div key={path} className="mono" title={info?.hash ?? ""}>
                  {path} @ {(info?.hash ?? "").slice(0, 7)}
                </div>
              ))}
            </div>
          </>
        )}
      </div>
      <ChangelogSection ws={ws} app={app} verstr={node.verstr} olderVerstrs={olderVerstrs} />
    </>
  );
});
