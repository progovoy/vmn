import { describe, it, expect } from "vitest";
import { layout } from "../pages/StampTree/layout";
import type { VersionRow } from "../types";

// A promoted release sharing its rc's commit on a feature branch, and two
// patch-line versions on main: positions captured from the StampTree page
// before its layout moved into its own module.
const row = (r: Partial<VersionRow> & { verstr: string }): VersionRow => ({
  tag: `app_${r.verstr}`, kind: "version", ...r,
});

const FIXTURE: VersionRow[] = [
  row({ verstr: "0.1.0", commit: "c1", branch: "main", release_mode: "minor", timestamp: 100 }),
  row({
    verstr: "0.2.0-rc.1", commit: "c2", branch: "feature/a-much-longer-branch",
    release_mode: "prerelease", prerelease: "rc", timestamp: 200, previous_version: "0.1.0",
  }),
  row({
    verstr: "0.2.0", commit: "c2", branch: "feature/a-much-longer-branch",
    release_mode: "release", prerelease: "release", timestamp: 210, previous_version: "0.2.0-rc.1",
  }),
  row({ verstr: "0.1.1", commit: "c3", branch: "main", release_mode: "patch", timestamp: 300, previous_version: "0.1.0" }),
];

describe("stamp tree layout", () => {
  const out = layout(FIXTURE);

  it("places nodes newest first, one lane per branch, merging a commit's tags", () => {
    expect(out.nodes.map((n) => ({
      verstr: n.verstr, mode: n.mode, prerelease: n.prerelease,
      aliases: n.aliases, x: n.x, y: n.y,
    }))).toEqual([
      { verstr: "0.1.1", mode: "patch", prerelease: null, aliases: [], x: 20, y: 36 },
      { verstr: "0.2.0", mode: "release", prerelease: null, aliases: ["0.2.0-rc.1"], x: 46, y: 80 },
      { verstr: "0.1.0", mode: "minor", prerelease: null, aliases: [], x: 20, y: 124 },
    ]);
  });

  it("draws one edge per canonical parent", () => {
    expect(out.edges).toEqual([["0.1.0", "0.2.0"], ["0.1.0", "0.1.1"]]);
    expect(out.canonical.get("0.2.0-rc.1")).toBe("0.2.0");
  });

  it("puts labels after the lanes and sizes the scroll extent from the widest label", () => {
    expect(out.textX).toBe(86);
    expect(out.labelEnd).toBeCloseTo(384.4);
    expect(out.presentModes).toEqual(["minor", "patch", "release"]);
  });

  it("keeps a minimum scroll extent for short labels", () => {
    expect(layout([FIXTURE[0]]).labelEnd).toBe(360);
  });
});
