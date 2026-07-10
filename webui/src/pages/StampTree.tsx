import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { api } from "../api";
import type { AppConfig, Changelog, VersionRow } from "../types";
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
  aliases: string[];
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

/** The release version an rc/build verstr belongs to ("0.9.1-rc.15" -> "0.9.1"). */
const baseVersion = (verstr: string) => verstr.split(/[-+]/)[0];

/** Canonical-node order within a commit: release, then rc, then metadata. */
const rowRank = (v: VersionRow) =>
  v.prerelease === "metadata" ? 2 : !v.prerelease || v.prerelease === "release" ? 0 : 1;

/** "0.9.1-rc.15" shown next to node "0.9.1" shortens to "rc.15". */
const shortAlias = (alias: string, verstr: string) =>
  alias.startsWith(verstr) ? alias.slice(verstr.length).replace(/^-/, "") : alias;

/** Lay out newest->oldest top->bottom; one narrow lane per branch.
 * Tags sharing a commit (a promoted release, its final rc, build metadata)
 * merge into one node — the release — with the rest as aliases. */
function layout(versions: VersionRow[]) {
  const groups: VersionRow[][] = [];
  const byKey = new Map<string, VersionRow[]>();
  versions.forEach((v) => {
    const key = `${v.commit}|${baseVersion(v.verstr)}`;
    const group = v.commit ? byKey.get(key) : undefined;
    if (group) {
      group.push(v);
    } else {
      const g = [v];
      byKey.set(key, g);
      groups.push(g);
    }
  });
  groups.forEach((g) => g.sort((a, b) => rowRank(a) - rowRank(b)));
  const canonical = new Map<string, string>();
  groups.forEach((g) => g.forEach((v) => canonical.set(v.verstr, g[0].verstr)));

  const ordered = [...groups].sort(
    (a, b) => (b[0].timestamp ?? 0) - (a[0].timestamp ?? 0)
  );
  const lanes: string[] = [];
  const nodes: Node[] = ordered.map((g, i) => {
    const v = g[0];
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
      aliases: g.slice(1).map((r) => r.verstr),
      x: PAD_LEFT + lane * LANE_W,
      y: PAD_TOP + ROW_H / 2 + i * ROW_H,
    };
  });
  const edges: [string, string][] = [];
  const seen = new Set<string>();
  versions.forEach((v) => {
    const from = v.previous_version && canonical.get(v.previous_version);
    const to = canonical.get(v.verstr)!;
    if (!from || from === to || seen.has(`${from}>${to}`)) return;
    seen.add(`${from}>${to}`);
    edges.push([from, to]);
  });

  const textX = PAD_LEFT + lanes.length * LANE_W + 14;
  const labelEnd = Math.max(
    360,
    ...nodes.map((n) => {
      const aliasChars = n.aliases.reduce(
        (len, a) => len + shortAlias(a, n.verstr).length + 3, 0
      );
      return (
        textX + (n.verstr.length + aliasChars) * VERSTR_CH +
        14 + n.branch.length * BRANCH_CH
      );
    })
  );
  const presentModes = Object.keys(MODE_COLOR).filter((m) =>
    nodes.some((n) => n.mode === m)
  );
  return { nodes, edges, canonical, textX, labelEnd, presentModes };
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

function CommitLine({ scope, description, hash }: Changelog["breaking"][number]) {
  return (
    <div style={{ display: "flex", gap: 6, alignItems: "baseline", lineHeight: 1.5 }}>
      <span className="mono" style={{ color: "var(--text-muted)", fontSize: 11 }}>{hash}</span>
      <span>
        {scope && <strong>{scope}: </strong>}
        {description}
      </span>
    </div>
  );
}

const CHANGELOG_COLLAPSED = 8; // commits shown before "show all"

function ChangelogBody({ cl }: { cl: Changelog }) {
  const [expanded, setExpanded] = useState(false);
  useEffect(() => setExpanded(false), [cl]);

  const sections = [
    ...(cl.breaking.length ? [{ label: "Breaking", breaking: true, commits: cl.breaking }] : []),
    ...cl.groups.map((g) => ({ label: g.label, breaking: false, commits: g.commits })),
  ];
  const total = sections.reduce((n, s) => n + s.commits.length, 0);
  if (total === 0) {
    return <div style={{ color: "var(--text-muted)" }}>No changes in this range.</div>;
  }

  // Keep section headers but stop rendering commits once the budget runs out.
  let budget = expanded ? Infinity : CHANGELOG_COLLAPSED;
  const shown = [];
  for (const s of sections) {
    if (budget <= 0) break;
    const commits = s.commits.slice(0, budget);
    budget -= commits.length;
    shown.push({ ...s, commits });
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 8 }}>
      {shown.map((s) => (
        <div key={s.label}>
          {s.breaking ? (
            <div className="badge mode-major" style={{ marginBottom: 4 }}>Breaking</div>
          ) : (
            <div style={{ fontWeight: 600, marginBottom: 4 }}>{s.label}</div>
          )}
          {s.commits.map((c) => <CommitLine key={c.hash} {...c} />)}
        </div>
      ))}
      {total > CHANGELOG_COLLAPSED && (
        <button
          style={{ alignSelf: "flex-start", padding: "2px 10px", fontSize: 12 }}
          onClick={() => setExpanded((e) => !e)}
        >
          {expanded ? "show less" : `show all ${total}`}
        </button>
      )}
    </div>
  );
}

/** Collapsed-by-default changelog: 'to' is the selected version, 'from' is a
 * dropdown over older versions (defaults to the previous one). */
function ChangelogSection({ ws, app, verstr, olderVerstrs }: {
  ws: string; app: string; verstr: string; olderVerstrs: string[];
}) {
  const [open, setOpen] = useState(false);
  const [from, setFrom] = useState<string | null>(null);
  const [cl, setCl] = useState<Changelog | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Reset when the selected version changes; 'from' falls back to the previous.
  useEffect(() => {
    setOpen(false);
    setFrom(null);
    setCl(null);
    setError(null);
  }, [verstr]);

  const effectiveFrom = from ?? olderVerstrs[0] ?? null;

  useEffect(() => {
    if (!open) return;
    let live = true;
    setCl(null);
    setError(null);
    api.changelog(ws, app, verstr, effectiveFrom ?? undefined)
      .then((c) => live && setCl(c))
      .catch((e) => live && setError(String(e)));
    return () => { live = false; };
  }, [open, ws, app, verstr, effectiveFrom]);

  return (
    <div style={{ marginTop: 16 }}>
      <Disclosure open={open} onToggle={() => setOpen((o) => !o)} label="changelog" />
      {open && (
        <>
          {olderVerstrs.length > 0 ? (
            <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 8, flexWrap: "wrap" }}>
              <span style={{ color: "var(--text-muted)", fontSize: 12 }}>from</span>
              <select
                className="mono"
                value={effectiveFrom ?? ""}
                onChange={(e) => setFrom(e.target.value)}
                style={{ fontSize: 12, padding: "1px 4px" }}
              >
                {olderVerstrs.map((v) => (
                  <option key={v} value={v}>{v}</option>
                ))}
              </select>
              <span style={{ color: "var(--text-muted)", fontSize: 12 }}>to</span>
              <span className="mono" style={{ fontSize: 12 }}>{verstr}</span>
            </div>
          ) : (
            <div style={{ color: "var(--text-muted)", marginTop: 8 }}>
              Baseline version — no previous.
            </div>
          )}
          {error && <div className="error" style={{ marginTop: 8 }}>{error}</div>}
          {olderVerstrs.length > 0 && cl && <ChangelogBody cl={cl} />}
        </>
      )}
    </div>
  );
}

/** Disclosure header shared by the changelog and config sections. */
function Disclosure({ open, onToggle, label }: {
  open: boolean; onToggle: () => void; label: string;
}) {
  return (
    <button
      onClick={onToggle}
      style={{
        background: "none", border: "none", padding: 0, cursor: "pointer",
        font: "inherit", fontWeight: 600, color: "var(--text-primary)",
        display: "flex", alignItems: "center", gap: 6,
      }}
    >
      <span style={{ color: "var(--text-muted)" }}>{open ? "▾" : "▸"}</span>
      {label}
    </button>
  );
}

/** App-level config + dependency repos, collapsed by default. */
/** Empty containers and nulls are vmn's "not configured" — hidden for clarity. */
const isDefaultConfValue = (v: unknown) =>
  v == null ||
  (Array.isArray(v) && v.length === 0) ||
  (typeof v === "object" && !Array.isArray(v) && Object.keys(v as object).length === 0);

const isPlainObject = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);

/** An indented block for a nested config value. */
function ConfNested({ children }: { children: ReactNode }) {
  return (
    <div style={{ borderLeft: "2px solid var(--border)", paddingLeft: 10, marginTop: 3 }}>
      {children}
    </div>
  );
}

function ConfValue({ v }: { v: unknown }) {
  if (Array.isArray(v)) {
    if (v.every((x) => !isPlainObject(x))) {
      return <span className="mono" style={{ fontSize: 12 }}>{v.join(", ")}</span>;
    }
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
        {v.map((x, i) =>
          isPlainObject(x) ? <ConfNested key={i}><ConfEntries obj={x} /></ConfNested>
            : <ConfValue key={i} v={x} />
        )}
      </div>
    );
  }
  return (
    <span className="mono" style={{ fontSize: 12, wordBreak: "break-word" }}>
      {String(v)}
    </span>
  );
}

/** Key/value rows; nested objects break onto their own indented block. */
function ConfEntries({ obj }: { obj: Record<string, unknown> }) {
  const entries = Object.entries(obj).filter(([, v]) => !isDefaultConfValue(v));
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
      {entries.map(([k, v]) =>
        isPlainObject(v) ? (
          <div key={k}>
            <div className="k">{k}</div>
            <ConfNested><ConfEntries obj={v} /></ConfNested>
          </div>
        ) : (
          <div key={k} style={{ display: "flex", gap: 10, alignItems: "baseline" }}>
            <span className="k" style={{ flexShrink: 0 }}>{k}</span>
            <ConfValue v={v} />
          </div>
        )
      )}
    </div>
  );
}

function ConfigSection({ ws, app }: { ws: string; app: string }) {
  const [open, setOpen] = useState(false);
  const [cfg, setCfg] = useState<AppConfig | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let live = true;
    setCfg(null);
    setError(null);
    api.config(ws, app).then((c) => live && setCfg(c)).catch((e) => live && setError(String(e)));
    return () => { live = false; };
  }, [open, ws, app]);

  const conf = cfg
    ? Object.fromEntries(
        Object.entries(cfg.conf).filter(
          ([k, v]) => k !== "deps" && !isDefaultConfValue(v)
        )
      )
    : {};

  return (
    <div style={{ marginTop: 16 }}>
      <Disclosure open={open} onToggle={() => setOpen((o) => !o)} label="config & deps" />
      {open && (
        <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 12 }}>
          {error && <div className="error">{error}</div>}
          {cfg && (
            <>
              <div>
                <div style={{ fontWeight: 600, marginBottom: 4 }}>deps</div>
                {cfg.deps.length === 0 ? (
                  <div style={{ color: "var(--text-muted)" }}>none configured</div>
                ) : (
                  cfg.deps.map((d) => (
                    <div key={d.path} className="mono" style={{ fontSize: 12 }} title={d.remote ?? ""}>
                      {d.path}{d.branch ? ` @${d.branch}` : ""}
                      <span style={{ color: "var(--text-muted)" }}> · {d.remote ?? "?"}</span>
                    </div>
                  ))
                )}
              </div>
              <div>
                <div style={{ fontWeight: 600, marginBottom: 4 }}>conf.yml</div>
                {Object.keys(conf).length === 0 ? (
                  <div style={{ color: "var(--text-muted)" }}>defaults (no overrides)</div>
                ) : (
                  <ConfEntries obj={conf} />
                )}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

const VersionDetails = memo(function VersionDetails({
  ws, app, node, canonical, edges, olderVerstrs, onSelect,
}: {
  ws: string;
  app: string;
  node: Node;
  canonical: Map<string, string>;
  edges: [string, string][];
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
  const { nodes, edges, canonical, textX, labelEnd, presentModes } = useMemo(
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
  const current =
    (selected && byVerstr[canonical.get(selected) ?? selected]) || nodes[0];
  // Versions older than the selected one (nodes are newest-first) — the
  // candidates for the changelog "from" dropdown.
  const olderVerstrs = useMemo(() => {
    const i = current ? nodes.findIndex((n) => n.verstr === current.verstr) : -1;
    return i < 0 ? [] : nodes.slice(i + 1).map((n) => n.verstr);
  }, [nodes, current]);

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
                      {n.aliases.length > 0 && (
                        <tspan dx="10" fill="var(--text-muted)" fontSize="11">
                          {n.aliases.map((a) => shortAlias(a, n.verstr)).join(" · ")}
                        </tspan>
                      )}
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

          <aside
            className="card"
            style={{
              flex: "1 1 280px", maxWidth: 360, position: "sticky", top: 16,
              maxHeight: "calc(100vh - 32px)", overflowY: "auto",
            }}
          >
            <VersionDetails ws={ws} app={app} node={current} canonical={canonical} edges={edges} olderVerstrs={olderVerstrs} onSelect={select} />
            <ConfigSection ws={ws} app={app} />
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
