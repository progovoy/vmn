import { describe, it, expect } from "vitest";
import { crumbsFor } from "../crumbs";
import type { CrumbInput, RouteId } from "../contracts";

const input = (routeId: RouteId, extra: Partial<CrumbInput> = {}, search = ""): CrumbInput => ({
  routeId, ws: "ml-repo", app: "ml_app", appTag: "ml_app",
  params: {}, search: new URLSearchParams(search), ...extra,
});
const labels = (i: CrumbInput) => crumbsFor(i).map((c) => c.label);
const BASE = "/ws/ml-repo/app/ml_app";
const last = <T,>(xs: T[]) => xs[xs.length - 1];

describe("crumbsFor", () => {
  it("global and workspace routes have one leaf", () => {
    expect(labels(input("home"))).toEqual(["workspaces"]);
    expect(labels(input("apps"))).toEqual(["apps"]);
    expect(labels(input("tokens"))).toEqual(["API tokens"]);
    expect(labels(input("not-found"))).toEqual(["not found"]);
    expect(labels(input("sign-in"))).toEqual(["sign in"]);
  });

  it("experiments: the app (mono, not a self-link) then the place", () => {
    const [app, leaf] = crumbsFor(input("experiments"));
    expect(app).toMatchObject({ label: "ml_app", mono: true });
    expect(app.to).toBeUndefined();
    expect(leaf.label).toBe("experiments");
    expect(leaf.to).toBeUndefined();
  });

  it("app routes link back to the leaderboard", () => {
    const [app, exps] = crumbsFor(input("code-diff", {}, "v=%401&to=latest"));
    expect(app.to).toBe(BASE);
    expect(exps).toMatchObject({ label: "experiments", to: BASE });
    expect(labels(input("code-diff", {}, "v=%401&to=latest")))
      .toEqual(["ml_app", "experiments", "diff @1 → latest"]);
    expect(last(labels(input("code-diff")))).toBe("diff @1 → latest");
    expect(labels(input("compare-runs", {}, "sel=a&sel=b&sel=c")))
      .toEqual(["ml_app", "experiments", "compare 3 runs"]);
    expect(labels(input("overlay", {}, "runs=a,b,c,d")))
      .toEqual(["ml_app", "experiments", "overlay 4 runs"]);
    expect(labels(input("actions"))).toEqual(["ml_app", "actions"]);
  });

  it("compare counts the runs the page shows: deduped, no blanks", () => {
    expect(last(labels(input("compare-runs", {}, "sel=a&sel=a&sel=&sel=b")))).toBe("compare 2 runs");
  });

  it("tree: the version is a mono leaf after a linked stamp tree", () => {
    expect(labels(input("tree"))).toEqual(["ml_app", "stamp tree"]);
    const crumbs = crumbsFor(input("tree", {}, "v=0.4.1"));
    expect(crumbs.map((c) => c.label)).toEqual(["ml_app", "stamp tree", "0.4.1"]);
    expect(crumbs[1].to).toBe(`${BASE}/tree`);
    expect(crumbs[2].mono).toBe(true);
  });

  it("run: @N and name, with the full verstr as title", () => {
    const run = { verstr: "0.4.1-dev.abcdef1234567890", idx: 54, name: "lr-sweep-3" };
    const crumbs = crumbsFor(input("run", { run, params: { verstr: "@54" } }));
    expect(crumbs.map((c) => c.label)).toEqual(["ml_app", "experiments", "@54 lr-sweep-3"]);
    expect(last(crumbs)).toMatchObject({ label: "@54 lr-sweep-3", title: run.verstr, run, mono: true });
  });

  it("run: @N alone without a name", () => {
    const run = { verstr: "0.4.1-dev.abc", idx: 54, name: null };
    expect(last(crumbsFor(input("run", { run })))!.label).toBe("@54");
  });

  it("run: a middle-truncated verstr without an idx", () => {
    const verstr = "0.4.1-dev.1700000000.abcdef1234567890";
    const leaf = last(crumbsFor(input("run", { params: { verstr } })))!;
    expect(leaf.label).toHaveLength(24);
    expect(leaf.label.endsWith("34567890")).toBe(true);
    expect(leaf.label).toContain("…");
    expect(leaf.title).toBe(verstr);
    expect(leaf.run).toEqual({ verstr, idx: null, name: null });
  });

  it("models and reports nest under their lists", () => {
    expect(labels(input("models"))).toEqual(["models"]);
    const model = crumbsFor(input("model", { params: { modelName: "resnet" } }));
    expect(model.map((c) => c.label)).toEqual(["models", "resnet"]);
    expect(model[0].to).toBe("/ws/ml-repo/models");
    expect(model[1].mono).toBe(true);
    expect(labels(input("reports"))).toEqual(["reports"]);
    expect(labels(input("report", { params: { rid: "r1" } }))).toEqual(["reports", "r1"]);
    expect(labels(input("report", { params: { rid: "r1" }, reportTitle: "Q3" }))).toEqual(["reports", "Q3"]);
    const edit = crumbsFor(input("report-edit", { params: { rid: "r1" }, reportTitle: "Q3" }));
    expect(edit.map((c) => c.label)).toEqual(["reports", "Q3", "edit"]);
    expect(edit[1].to).toBe("/ws/ml-repo/reports/r1");
  });
});
