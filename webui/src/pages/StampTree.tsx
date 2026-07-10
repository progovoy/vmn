import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api";
import type { VersionRow } from "../types";
import { AppLayoutNav } from "./Leaderboard";

const MODE_COLOR: Record<string, string> = {
  major: "var(--series-6)",
  minor: "var(--series-1)",
  patch: "var(--series-2)",
  hotfix: "var(--series-3)",
  init: "var(--text-muted)",
  prerelease: "var(--series-3)",
};

interface Node {
  verstr: string;
  base: string;
  mode: string;
  prerelease: string | null;
  branch: string | null;
  commit: string | null;
  x: number;
  y: number;
}

const ROW_H = 64;
const COL_W = 190;
const R = 9;

/** Lay out the version chain oldest->newest top->bottom; branch lanes by column. */
function layout(versions: VersionRow[]): { nodes: Node[]; edges: [string, string][] } {
  const ordered = [...versions].sort((a, b) => (a.timestamp ?? 0) - (b.timestamp ?? 0));
  const lanes: string[] = [];
  const nodes: Node[] = [];
  ordered.forEach((v, i) => {
    const branch = v.branch ?? "?";
    let lane = lanes.indexOf(branch);
    if (lane < 0) {
      lane = lanes.length;
      lanes.push(branch);
    }
    nodes.push({
      verstr: v.verstr,
      base: v.verstr,
      mode: v.release_mode ?? "?",
      prerelease: v.prerelease && v.prerelease !== "release" ? v.prerelease : null,
      branch,
      commit: v.commit ?? null,
      x: 40 + lane * COL_W,
      y: 40 + i * ROW_H,
    });
  });
  const known = new Set(nodes.map((n) => n.verstr));
  const edges: [string, string][] = [];
  ordered.forEach((v) => {
    if (v.previous_version && known.has(v.previous_version)) {
      edges.push([v.previous_version, v.verstr]);
    }
  });
  return { nodes, edges };
}

export default function StampTree() {
  const { ws, app } = useParams() as { ws: string; app: string };
  const [rows, setRows] = useState<VersionRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    api.versions(ws, app).then(setRows).catch((e) => setError(String(e)));
  }, [ws, app]);

  const versions = useMemo(
    () => (rows ?? []).filter((r) => r.kind === "version"),
    [rows]
  );
  const roots = useMemo(
    () => (rows ?? []).filter((r) => r.kind === "root"),
    [rows]
  );
  const { nodes, edges } = useMemo(() => layout(versions), [versions]);
  const byVerstr = useMemo(
    () => Object.fromEntries(nodes.map((n) => [n.verstr, n])),
    [nodes]
  );

  if (error) return <div className="error">{error}</div>;
  if (rows === null) return <div className="empty">Loading…</div>;

  const height = nodes.length ? 40 + nodes.length * ROW_H : 100;
  const width = Math.max(
    360,
    40 + (new Set(nodes.map((n) => n.x)).size) * COL_W
  );

  return (
    <>
      <h1>{app.replaceAll("-", "/")}</h1>
      <AppLayoutNav />

      {nodes.length === 0 && roots.length === 0 ? (
        <div className="empty">No stamped versions yet.</div>
      ) : (
        <div className="card" style={{ display: "flex", gap: 16 }}>
          <svg width={width} height={height} style={{ flexShrink: 0 }}>
            {edges.map(([from, to], i) => {
              const a = byVerstr[from];
              const b = byVerstr[to];
              if (!a || !b) return null;
              return (
                <path
                  key={i}
                  d={`M${a.x},${a.y} C${a.x},${(a.y + b.y) / 2} ${b.x},${(a.y + b.y) / 2} ${b.x},${b.y}`}
                  fill="none"
                  stroke="var(--border)"
                  strokeWidth={2}
                />
              );
            })}
            {nodes.map((n) => (
              <g
                key={n.verstr}
                style={{ cursor: "pointer" }}
                onClick={() => setSelected(n.verstr)}
              >
                <circle
                  cx={n.x}
                  cy={n.y}
                  r={selected === n.verstr ? R + 2 : R}
                  fill={MODE_COLOR[n.mode] ?? "var(--text-muted)"}
                  stroke="var(--surface-1)"
                  strokeWidth={2}
                />
                <text
                  x={n.x + R + 8}
                  y={n.y + 4}
                  fill="var(--text-primary)"
                  fontSize="12.5"
                  fontFamily="ui-monospace, monospace"
                >
                  {n.verstr}
                </text>
              </g>
            ))}
          </svg>

          <div style={{ minWidth: 200 }}>
            <h2 style={{ marginTop: 0 }}>legend</h2>
            {Object.entries(MODE_COLOR).map(([mode, color]) => (
              <div key={mode} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                <span style={{ width: 12, height: 12, borderRadius: "50%", background: color, display: "inline-block" }} />
                <span style={{ color: "var(--text-secondary)" }}>{mode}</span>
              </div>
            ))}
            {selected && byVerstr[selected] && (
              <div style={{ marginTop: 16 }}>
                <h2>{selected}</h2>
                <div className="kv">
                  <div className="k">mode</div>
                  <div>{byVerstr[selected].mode}</div>
                  <div className="k">branch</div>
                  <div className="mono">{byVerstr[selected].branch}</div>
                  <div className="k">commit</div>
                  <div className="mono">{byVerstr[selected].commit?.slice(0, 7)}</div>
                </div>
              </div>
            )}
          </div>
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
