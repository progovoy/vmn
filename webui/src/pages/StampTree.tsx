import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { api } from "../api";
import type { VersionRow } from "../types";
import { AppLayoutNav } from "./Leaderboard";
import { copyText, relTime } from "../util";

const MODE_COLOR: Record<string, string> = {
  major: "var(--series-6)",
  minor: "var(--series-1)",
  patch: "var(--series-2)",
  hotfix: "var(--series-3)",
  prerelease: "var(--series-5)",
  release: "var(--series-5)",
  init: "var(--text-muted)",
};

const isPrerelease = (mode: string) => mode === "prerelease";

interface Node {
  verstr: string;
  mode: string;
  prerelease: string | null;
  branch: string;
  rel: string;
  row: VersionRow;
  x: number;
  y: number;
}

const ROW_H = 44;
const LANE_W = 26;
const R = 6.5;
const PAD_TOP = 14;
const PAD_LEFT = 20;
// Monospace advances, used only to estimate the SVG's horizontal scroll extent
// (labelEnd) — never to place text, which flows via <tspan>.
const VERSTR_CH = 7.6; // at 12.5px
const BRANCH_CH = 6.9; // at 11.5px

function fmtDate(ts: number | null | undefined): string {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleString(undefined, {
    year: "numeric", month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

function relDate(ts: number | null | undefined): string {
  return ts ? relTime(new Date(ts * 1000).toISOString()) : "";
}

/** Lay out newest->oldest top->bottom; one narrow lane per branch. */
function layout(versions: VersionRow[]) {
  const ordered = [...versions].sort((a, b) => (b.timestamp ?? 0) - (a.timestamp ?? 0));
  const lanes: string[] = [];
  const nodes: Node[] = ordered.map((v, i) => {
    const branch = v.branch ?? "?";
    let lane = lanes.indexOf(branch);
    if (lane < 0) {
      lane = lanes.length;
      lanes.push(branch);
    }
    return {
      verstr: v.verstr,
      mode: v.release_mode ?? "?",
      prerelease: v.prerelease && v.prerelease !== "release" ? v.prerelease : null,
      branch,
      rel: relDate(v.timestamp),
      row: v,
      x: PAD_LEFT + lane * LANE_W,
      y: PAD_TOP + ROW_H / 2 + i * ROW_H,
    };
  });
  const known = new Set(nodes.map((n) => n.verstr));
  const edges: [string, string][] = [];
  ordered.forEach((v) => {
    if (
      v.previous_version &&
      v.previous_version !== v.verstr &&
      known.has(v.previous_version)
    ) {
      edges.push([v.previous_version, v.verstr]);
    }
  });

  const textX = PAD_LEFT + lanes.length * LANE_W + 14;
  const labelEnd = Math.max(
    360,
    ...nodes.map(
      (n) => textX + n.verstr.length * VERSTR_CH + 14 + n.branch.length * BRANCH_CH
    )
  );
  const presentModes = Object.keys(MODE_COLOR).filter((m) =>
    nodes.some((n) => n.mode === m)
  );
  return { nodes, edges, textX, labelEnd, presentModes };
}

function ModeDot({ mode }: { mode: string }) {
  const color = MODE_COLOR[mode] ?? "var(--text-muted)";
  return (
    <span
      style={{
        width: 10, height: 10, borderRadius: "50%", display: "inline-block",
        flexShrink: 0,
        background: isPrerelease(mode) ? "transparent" : color,
        border: `2px solid ${color}`,
      }}
    />
  );
}

const VersionDetails = memo(function VersionDetails({
  node, byVerstr, edges, onSelect,
}: {
  node: Node;
  byVerstr: Record<string, Node>;
  edges: [string, string][];
  onSelect: (verstr: string) => void;
}) {
  const [copied, setCopied] = useState<"copied" | "no clipboard" | null>(null);
  useEffect(() => setCopied(null), [node.verstr]);

  const prev = node.row.previous_version;
  const next = edges.filter(([from]) => from === node.verstr).map(([, to]) => to);
  const deps = Object.entries(node.row.changesets ?? {}).filter(([p]) => p !== ".");

  const versionLink = (v: string) =>
    byVerstr[v] ? (
      <a key={v} onClick={() => onSelect(v)} style={{ cursor: "pointer", marginRight: 10 }} className="mono">
        {v}
      </a>
    ) : (
      <span key={v} className="mono" style={{ marginRight: 10 }}>{v}</span>
    );

  return (
    <>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <span className="mono" style={{ fontSize: 16, fontWeight: 600 }}>{node.verstr}</span>
        <span className={`badge mode-${node.mode}`}>{node.mode}</span>
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
    </>
  );
});

export default function StampTree() {
  const { ws, app } = useParams() as { ws: string; app: string };
  const [rows, setRows] = useState<VersionRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [params, setParams] = useSearchParams();
  const selected = params.get("v");
  const graphRef = useRef<HTMLDivElement | null>(null);
  const [graphW, setGraphW] = useState(0);

  useEffect(() => {
    api.versions(ws, app).then(setRows).catch((e) => setError(String(e)));
  }, [ws, app]);

  useEffect(() => {
    const el = graphRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) =>
      setGraphW(entries[0].contentRect.width)
    );
    ro.observe(el);
    return () => ro.disconnect();
  }, [rows]);

  const versions = useMemo(
    () => (rows ?? []).filter((r) => r.kind === "version"),
    [rows]
  );
  const roots = useMemo(
    () => (rows ?? []).filter((r) => r.kind === "root"),
    [rows]
  );
  const { nodes, edges, textX, labelEnd, presentModes } = useMemo(
    () => layout(versions),
    [versions]
  );
  const byVerstr = useMemo<Record<string, Node>>(
    () => Object.fromEntries(nodes.map((n) => [n.verstr, n])),
    [nodes]
  );
  const select = useCallback(
    (verstr: string) => setParams({ v: verstr }, { replace: true }),
    [setParams]
  );
  const current = (selected && byVerstr[selected]) || nodes[0];

  if (error) return <div className="error">{error}</div>;
  if (rows === null) return <div className="empty">Loading…</div>;

  const width = Math.max(labelEnd + 110, graphW);
  const height = PAD_TOP + nodes.length * ROW_H + 8;

  return (
    <>
      <h1>{app.replaceAll("-", "/")}</h1>
      <AppLayoutNav />

      {nodes.length === 0 && roots.length === 0 && (
        <div className="empty">No stamped versions yet.</div>
      )}

      {nodes.length > 0 && (
        <div style={{ display: "flex", gap: 16, alignItems: "flex-start", flexWrap: "wrap" }}>
          <div ref={graphRef} className="card" style={{ flex: "1 1 320px", minWidth: 0, overflowX: "auto", padding: "8px 6px" }}>
            <svg width={width} height={height} style={{ display: "block" }}>
              {nodes.map((n) => (
                <rect
                  key={n.verstr}
                  className={`tree-row${current.verstr === n.verstr ? " selected" : ""}`}
                  x={2} y={n.y - ROW_H / 2} width={width - 4} height={ROW_H} rx={6}
                  onClick={() => select(n.verstr)}
                />
              ))}
              {edges.map(([from, to], i) => {
                const a = byVerstr[from];
                const b = byVerstr[to];
                if (!a || !b) return null;
                const active = from === current.verstr || to === current.verstr;
                return (
                  <path
                    key={i}
                    d={`M${a.x},${a.y} C${a.x},${(a.y + b.y) / 2} ${b.x},${(a.y + b.y) / 2} ${b.x},${b.y}`}
                    fill="none"
                    stroke={active ? "var(--accent)" : "var(--border)"}
                    strokeWidth={2}
                    pointerEvents="none"
                  />
                );
              })}
              {nodes.map((n) => {
                const color = MODE_COLOR[n.mode] ?? "var(--text-muted)";
                const hollow = isPrerelease(n.mode);
                return (
                  <g key={n.verstr} pointerEvents="none">
                    {current.verstr === n.verstr && (
                      <circle cx={n.x} cy={n.y} r={R + 4} fill="none"
                        stroke="var(--accent)" strokeWidth={1.5} />
                    )}
                    <circle
                      cx={n.x} cy={n.y} r={R}
                      fill={hollow ? "var(--surface-1)" : color}
                      stroke={hollow ? color : "var(--surface-1)"}
                      strokeWidth={2}
                    />
                    <text x={textX} y={n.y + 4} fontFamily="ui-monospace, monospace">
                      <tspan fill="var(--text-primary)" fontSize="12.5">{n.verstr}</tspan>
                      <tspan dx="14" fill="var(--text-muted)" fontSize="11.5">{n.branch}</tspan>
                    </text>
                    <text x={width - 12} y={n.y + 4} fill="var(--text-muted)"
                      fontSize="11.5" textAnchor="end">
                      {n.rel}
                    </text>
                  </g>
                );
              })}
            </svg>
          </div>

          <aside className="card" style={{ flex: "1 1 280px", maxWidth: 360, position: "sticky", top: 16 }}>
            <VersionDetails node={current} byVerstr={byVerstr} edges={edges} onSelect={select} />
            <h2>legend</h2>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {presentModes.map((mode) => (
                <div key={mode} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <ModeDot mode={mode} />
                  <span style={{ color: "var(--text-secondary)" }}>
                    {mode === "release" ? "release (promoted rc)" : mode}
                  </span>
                </div>
              ))}
            </div>
          </aside>
        </div>
      )}

      {roots.length > 0 && (
        <div className="card">
          <h2 style={{ marginTop: 0 }}>root versions → services</h2>
          {roots
            .slice()
            .sort((a, b) => (b.timestamp ?? 0) - (a.timestamp ?? 0))
            .map((r) => (
              <div key={r.tag} style={{ marginBottom: 10 }}>
                <span className="badge">root {r.verstr}</span>{" "}
                {Object.entries(r.services ?? {}).map(([s, ver]) => (
                  <span key={s} className="mono" style={{ marginRight: 12 }}>
                    {s}@{ver}
                  </span>
                ))}
              </div>
            ))}
        </div>
      )}
    </>
  );
}
