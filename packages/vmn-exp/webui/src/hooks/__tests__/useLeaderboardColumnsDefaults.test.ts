/** Plan 20 C1 (D11): the leaderboard's default columns. */
import { describe, it, expect } from "vitest";
import { renderHook } from "@testing-library/react";
import { useLeaderboardColumns } from "../useLeaderboardColumns";
import type { ExperimentRow, MetricsSchema } from "../../types";

const row = (i: number, metrics: Record<string, number>, params: Record<string, unknown> = {}): ExperimentRow => ({
  idx: i, verstr: `v${i}`, code_verstr: `v${i}`, timestamp: null, note: null,
  branch: "main", base_version: "0.0.1", params, metrics,
});

const SCHEMA: MetricsSchema = { val_loss: { goal: "min" }, val_acc: { goal: "max" } };
const ROWS = [
  row(1, { train_loss: 1, val_acc: 0.8, val_loss: 0.5 }, { a: 1, b: 1, c: 1, d: 1, e: 1, f: 1, g: 1, seed: 7 }),
  row(2, { train_loss: 2, val_acc: 0.9, val_loss: 0.4 }, { a: 2, b: 2, c: 2, d: 2, e: 2, f: 2, g: 2, seed: 7 }),
];
const none = new Set<string>();
const EMPTY: readonly string[] = [];
const PREFS = { widths: {}, order: [] as readonly string[] };

function columns(opts: {
  rows?: ExperimentRow[]; schema?: MetricsSchema | null; hidden?: Set<string>; shown?: Set<string>;
  pinned?: readonly string[]; order?: readonly string[]; fill?: number; prefs?: typeof PREFS;
} = {}) {
  const { result } = renderHook(() => useLeaderboardColumns(
    opts.rows ?? ROWS, opts.schema === undefined ? SCHEMA : opts.schema, opts.hidden ?? none, "", null,
    opts.order ?? EMPTY, opts.pinned ?? EMPTY, opts.prefs ?? PREFS, opts.fill ?? 0, opts.shown ?? none,
  ));
  return result.current;
}

const ids = (c: ReturnType<typeof columns>) => c.layout.ids ?? [];

describe("default leaderboard columns (D11)", () => {
  it("lead with the goal metrics, pinned right after the experiment column", () => {
    const c = columns();
    expect(ids(c).slice(0, 6)).toEqual(["check", "idx", "status", "experiment", "m:val_loss", "m:val_acc"]);
    expect(c.pinned).toEqual(["m:val_loss", "m:val_acc"]);
    expect(c.layout.styles[4].position).toBe("sticky");
    expect(c.layout.styles[5].position).toBe("sticky");
  });

  it("offer the other metrics in the picker without showing them", () => {
    const c = columns();
    expect(c.metricCols).toContain("train_loss");
    expect(c.visibleMetrics).toEqual(["val_loss", "val_acc"]);
    expect(ids(c)).not.toContain("m:train_loss");
  });

  it("show a non-goal metric once it is toggled on", () => {
    expect(columns({ hidden: new Set(["m:train_loss"]) }).visibleMetrics).toContain("train_loss");
  });

  it("keep every metric when the schema declares no goal", () => {
    expect(columns({ schema: null }).visibleMetrics.sort()).toEqual(["train_loss", "val_acc", "val_loss"]);
    expect(columns({ schema: null }).pinned).toEqual([]);
  });

  it("show at most six params, only ones whose values vary", () => {
    const c = columns();
    expect(c.paramCols).toContain("seed");
    expect(c.visibleParams).toHaveLength(6);
    expect(c.visibleParams).not.toContain("seed");
  });

  it("end with when, leaving note and the run's start/end dates to the picker", () => {
    const c = columns();
    expect(ids(c)[ids(c).length - 1]).toBe("when");
    for (const id of ["note", "c:started", "c:ended"]) expect(ids(c)).not.toContain(id);
    expect(c.otherCols).toEqual(expect.arrayContaining(["note", "started", "ended"]));
  });
});

describe("the user's choices beat the defaults", () => {
  it("a param shown in show= appears, constant or not", () => {
    expect(columns({ shown: new Set(["p:seed"]) }).visibleParams).toContain("seed");
  });

  it("a param in hide= stays hidden and frees its slot", () => {
    const c = columns({ hidden: new Set(["p:a"]) });
    expect(c.visibleParams).not.toContain("a");
    expect(c.visibleParams).toContain("g");
  });

  it("a hidden goal metric is not shown or pinned", () => {
    const c = columns({ hidden: new Set(["m:val_acc"]) });
    expect(c.visibleMetrics).toEqual(["val_loss"]);
    expect(c.pinned).toEqual(["m:val_loss"]);
  });

  it("pin= replaces the default pins, and the no-pins marker pins nothing", () => {
    expect(columns({ pinned: ["p:a"] }).pinned).toEqual(["p:a"]);
    const c = columns({ pinned: ["-"] });
    expect(c.pinned).toEqual([]);
    expect(c.layout.styles[4].position).toBeUndefined();
  });

  it("show= brings back note and the dates", () => {
    const c = columns({ shown: new Set(["c:note", "c:started", "c:ended"]) });
    expect(ids(c)).toEqual(expect.arrayContaining(["note", "c:started", "c:ended"]));
  });

  it("a saved drag order still wins over the default order", () => {
    const prefs = { widths: {}, order: ["when", "p:b", "p:a"] };
    const c = columns({ prefs, pinned: ["-"] });
    const rest = ids(c).slice(4);
    expect(rest.indexOf("when")).toBeLessThan(rest.indexOf("p:b"));
    expect(rest.indexOf("p:b")).toBeLessThan(rest.indexOf("p:a"));
  });
});

describe("fitting the table (F2)", () => {
  /** The table card's inner width on a 1280px-wide window. */
  const AT_1280 = 977;

  it("keeps the primary metric in view at 1280px and fills the width without overflowing", () => {
    const c = columns({ fill: AT_1280 });
    const i = ids(c).indexOf("m:val_loss");
    const style = c.layout.styles[i];
    expect(Number(style.left) + c.layout.widths![i]).toBeLessThanOrEqual(AT_1280);
    expect(c.layout.total).toBeLessThanOrEqual(AT_1280);
  });

  it("drops default params that would not fit, keeping the ones that do", () => {
    const narrow = columns({ fill: AT_1280 }).visibleParams.length;
    const wide = columns({ fill: 1137 }).visibleParams.length;
    expect(narrow).toBeLessThan(6);
    expect(wide).toBeGreaterThanOrEqual(narrow);
  });

  it("still fits at 1280px when an outer run adds the inner column", () => {
    const rows = [...ROWS, { ...row(3, { val_loss: 0.3 }), kind: "outer" as const, children: ["x"] }];
    const c = columns({ rows, fill: AT_1280 });
    expect(ids(c)).toContain("c:inner");
    expect(c.layout.total).toBeLessThanOrEqual(AT_1280);
  });
});
