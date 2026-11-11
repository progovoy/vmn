import type { VersionRow } from "../../types";
import { relTime } from "../../util";

export const MODE_COLOR: Record<string, string> = {
  major: "var(--major)",
  minor: "var(--minor)",
  patch: "var(--patch)",
  hotfix: "var(--hotfix)",
  prerelease: "var(--pre)",
  release: "var(--pre)",
  init: "var(--text-3)",
};

export const isPrerelease = (mode: string) => mode === "prerelease";

export interface Node {
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

export type Edge = [string, string];

export const ROW_H = 44;
const LANE_W = 26;
export const PAD_TOP = 14;
const PAD_LEFT = 20;
// Monospace advances, used only to estimate the SVG's horizontal scroll extent
// (labelEnd) — never to place text, which flows via <tspan>.
const VERSTR_CH = 7.6; // at 12.5px
const BRANCH_CH = 6.9; // at 11.5px

function relDate(ts: number | null | undefined): string {
  return ts ? relTime(new Date(ts * 1000).toISOString()) : "";
}

/** The release version an rc/build verstr belongs to ("0.9.1-rc.15" -> "0.9.1"). */
const baseVersion = (verstr: string) => verstr.split(/[-+]/)[0];

/** Canonical-node order within a commit: release, then rc, then metadata. */
const rowRank = (v: VersionRow) =>
  v.prerelease === "metadata" ? 2 : !v.prerelease || v.prerelease === "release" ? 0 : 1;

/** "0.9.1-rc.15" shown next to node "0.9.1" shortens to "rc.15". */
export const shortAlias = (alias: string, verstr: string) =>
  alias.startsWith(verstr) ? alias.slice(verstr.length).replace(/^-/, "") : alias;

/** Lay out newest->oldest top->bottom; one narrow lane per branch.
 * Tags sharing a commit (a promoted release, its final rc, build metadata)
 * merge into one node — the release — with the rest as aliases. */
export function layout(versions: VersionRow[]) {
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
  const edges: Edge[] = [];
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
