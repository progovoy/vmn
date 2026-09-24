import { describe, it, expect } from "vitest";
import {
  MAX_COMPARE_RUNS, compareRows, parseSelection, runLabel, withoutRun,
} from "../compareRunsData";
import type { ExperimentDetail } from "../../types";

const detail = (
  verstr: string, params: Record<string, unknown>, metrics: ExperimentDetail["metrics"],
  meta: Record<string, unknown> = {},
): ExperimentDetail => ({
  metadata: { verstr, ...meta }, params, metrics, series: {}, patches: {},
});

describe("parseSelection", () => {
  it("dedupes the repeated sel params in order", () => {
    const p = new URLSearchParams("sel=a&sel=b&sel=a&sel=c");
    expect(parseSelection(p)).toEqual({ verstrs: ["a", "b", "c"], dropped: 0 });
  });

  it("caps the selection and reports how many were dropped", () => {
    const p = new URLSearchParams();
    for (let i = 0; i < MAX_COMPARE_RUNS + 3; i++) p.append("sel", `v${i}`);
    const out = parseSelection(p);
    expect(out.verstrs).toHaveLength(MAX_COMPARE_RUNS);
    expect(out.dropped).toBe(3);
  });

  it("ignores empty values", () => {
    expect(parseSelection(new URLSearchParams("sel=&sel=a")).verstrs).toEqual(["a"]);
  });
});

describe("withoutRun", () => {
  it("drops one verstr and keeps every other param", () => {
    const p = new URLSearchParams("sel=a&sel=b&sel=c&diff=1");
    const next = withoutRun(p, "b");
    expect(next.getAll("sel")).toEqual(["a", "c"]);
    expect(next.get("diff")).toBe("1");
    expect(p.getAll("sel")).toEqual(["a", "b", "c"]);
  });
});

describe("runLabel", () => {
  it("prefers the run name, else the verstr", () => {
    expect(runLabel("v1", detail("v1", {}, {}, { name: "baseline" }))).toBe("baseline");
    expect(runLabel("v1", detail("v1", {}, {}, { name: null }))).toBe("v1");
    expect(runLabel("v1", undefined)).toBe("v1");
  });
});

describe("compareRows", () => {
  const runs = [
    detail("a", { lr: 0.1, model: "m1", only_a: true }, { loss: 0.3, acc: 0.8 }),
    detail("b", { lr: 0.1, model: "m2" }, { loss: 0.2, acc: 0.9, extra: 1 }),
    undefined,
  ];

  it("unions the param keys, sorted, with verbatim values and gaps for missing ones", () => {
    const rows = compareRows(runs, "params", null);
    expect(rows.map((r) => r.key)).toEqual(["lr", "model", "only_a"]);
    expect(rows[1].values).toEqual(["m1", "m2", undefined]);
    expect(rows[2].values).toEqual([true, undefined, undefined]);
  });

  it("marks a row differing only when the loaded runs disagree", () => {
    const rows = compareRows(runs, "params", null);
    expect(rows.find((r) => r.key === "lr")!.differs).toBe(false);
    expect(rows.find((r) => r.key === "model")!.differs).toBe(true);
    // Present in one run and missing in another is a difference.
    expect(rows.find((r) => r.key === "only_a")!.differs).toBe(true);
  });

  it("picks the best metric value by the goal", () => {
    const rows = compareRows(runs, "metrics", { acc: { goal: "max" } });
    expect(rows.find((r) => r.key === "loss")!.best).toBe(0.2);
    expect(rows.find((r) => r.key === "acc")!.best).toBe(0.9);
  });

  it("has no best with fewer than two numeric values, or when all are equal", () => {
    const rows = compareRows(
      [detail("a", {}, { extra: 1, same: 2 }), detail("b", {}, { extra: null, same: 2 })],
      "metrics", null,
    );
    expect(rows.find((r) => r.key === "extra")!.best).toBeNull();
    expect(rows.find((r) => r.key === "same")!.best).toBeNull();
  });

  it("treats params as not scored", () => {
    expect(compareRows(runs, "params", null).every((r) => r.best === null)).toBe(true);
  });
});
