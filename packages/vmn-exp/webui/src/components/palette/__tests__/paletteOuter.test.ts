/** ⌘K names an outer run's kind: `outer · N runs` in its secondary line. */
import { describe, it, expect } from "vitest";
import type { ExperimentRow } from "../../../types";
import { buildSections } from "../paletteItems";
import { parseCliQuery } from "../parseCliQuery";
import { fakeCtx } from "./fakeCtx";

const run = (idx: number, verstr: string, extra: Partial<ExperimentRow> = {}) =>
  ({ idx, verstr, name: null, note: null, timestamp: null, ...extra }) as ExperimentRow;

function runItems(runs: ExperimentRow[]) {
  const ctx = fakeCtx({ app: "ml_app" });
  const apps = [{ name: "ml_app", experiments: 3, versions: 0 }];
  const sections = buildSections({
    ctx, text: "", apps,
    intent: parseCliQuery("", { apps: ["ml_app"], workspaces: ctx.workspaces.map((w) => w.name), app: ctx.app }),
    refs: {}, runs, searched: false, models: [], reports: [], recents: [],
  });
  return sections.find((s) => s.key === "runs")!.items;
}

describe("⌘K's run rows", () => {
  it("say an outer run is one, with its run count", () => {
    const [outer, single] = runItems([
      run(3, "0.1.0-dev.o", { name: "kfold-cv", kind: "outer", children: ["a", "b", "c"], status: "succeeded" }),
      run(1, "0.1.0-dev.s", { kind: "single", children: [] }),
    ]);
    expect(outer.secondary).toMatch(/^outer · 3 runs/);
    expect(single.secondary ?? "").not.toMatch(/outer/);
  });
});
