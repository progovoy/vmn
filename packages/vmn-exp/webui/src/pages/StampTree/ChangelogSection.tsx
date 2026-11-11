import { useEffect, useState } from "react";
import { api } from "../../api";
import type { Changelog } from "../../types";
import { Disclosure } from "./Disclosure";

// Accent per conventional-commit group; anything else falls back to muted.
const GROUP_ACCENT: Record<string, string> = {
  Features: "var(--minor)",
  "Bug Fixes": "var(--patch)",
  "Performance Improvements": "var(--hotfix)",
};

function CommitLine({ scope, description, hash }: Changelog["breaking"][number]) {
  return (
    <div className="cl-commit">
      <span className="cl-hash mono">{hash}</span>
      <span className="cl-desc">
        {scope && <span className="cl-scope">{scope}</span>}
        {description}
      </span>
    </div>
  );
}

const CHANGELOG_COLLAPSED = 8; // commits shown before "show all"

/** Grouped conventional commits (breaking + type groups) with a collapse budget.
 * Shared by the app-level changelog and each per-dependency changelog. */
function CommitGroups({
  breaking, groups, resetKey, collapsedAt = CHANGELOG_COLLAPSED,
}: {
  breaking: Changelog["breaking"];
  groups: Changelog["groups"];
  resetKey: string;
  collapsedAt?: number;
}) {
  const [expanded, setExpanded] = useState(false);
  useEffect(() => setExpanded(false), [resetKey]);

  const sections = [
    ...(breaking.length ? [{ label: "Breaking", breaking: true, commits: breaking }] : []),
    ...groups.map((g) => ({ label: g.label, breaking: false, commits: g.commits })),
  ];
  const total = sections.reduce((n, s) => n + s.commits.length, 0);
  if (total === 0) {
    return <div className="cl-empty">No changes in this range.</div>;
  }

  // Keep section headers but stop rendering commits once the budget runs out.
  let budget = expanded ? Infinity : collapsedAt;
  const shown = [];
  for (const s of sections) {
    if (budget <= 0) break;
    const commits = s.commits.slice(0, budget);
    budget -= commits.length;
    shown.push({ ...s, commits });
  }

  return (
    <div className="cl-groups">
      {shown.map((s) => (
        <div key={s.label} className="cl-section">
          <div className="cl-section-head">
            {s.breaking ? (
              <span className="badge mode-major">Breaking</span>
            ) : (
              <>
                <span
                  className="cl-tag-dot"
                  style={{ background: GROUP_ACCENT[s.label] ?? "var(--text-muted)" }}
                />
                <span className="cl-section-label">{s.label}</span>
              </>
            )}
            <span className="cl-count">{s.commits.length}</span>
          </div>
          {s.commits.map((c) => <CommitLine key={c.hash} {...c} />)}
        </div>
      ))}
      {total > collapsedAt && (
        <button className="cl-more" onClick={() => setExpanded((e) => !e)}>
          {expanded ? "show less" : `show all ${total}`}
        </button>
      )}
    </div>
  );
}

/** One dependency's changelog: name, moved commit range, and its commits. */
function DepChangelog({ dep }: { dep: Changelog["deps"][number] }) {
  return (
    <div className="cl-dep">
      <div className="cl-dep-head">
        <span className="cl-dep-name">{dep.name}</span>
        <span className="cl-dep-range mono">
          {dep.from_commit}<span className="cl-dep-arrow">→</span>{dep.to_commit}
        </span>
      </div>
      <CommitGroups
        breaking={dep.breaking}
        groups={dep.groups}
        resetKey={dep.path + dep.to_commit}
        collapsedAt={5}
      />
    </div>
  );
}

function ChangelogBody({ cl }: { cl: Changelog }) {
  const resetKey = `${cl.from_verstr}->${cl.to_verstr}`;
  return (
    <div className="cl-body">
      <CommitGroups breaking={cl.breaking} groups={cl.groups} resetKey={resetKey} />
      {cl.deps.length > 0 && (
        <div className="cl-deps">
          <div className="cl-deps-head">
            dependencies<span className="cl-count">{cl.deps.length}</span>
          </div>
          {cl.deps.map((d) => <DepChangelog key={d.path} dep={d} />)}
        </div>
      )}
    </div>
  );
}

/** Collapsed-by-default changelog: 'to' is the selected version, 'from' is a
 * dropdown over older versions (defaults to the previous one). */
export function ChangelogSection({ ws, app, verstr, olderVerstrs }: {
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
              <span className="select-wrap" style={{ display: "inline-block" }}>
                <select
                  className="mono"
                  aria-label="Changelog from"
                  value={effectiveFrom ?? ""}
                  onChange={(e) => setFrom(e.target.value)}
                  style={{ fontSize: 12, padding: "3px 26px 3px 8px" }}
                >
                  {olderVerstrs.map((v) => (
                    <option key={v} value={v}>{v}</option>
                  ))}
                </select>
              </span>
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
