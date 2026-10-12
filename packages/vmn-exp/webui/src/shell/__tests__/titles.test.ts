import { describe, it, expect } from "vitest";
import { subjectFor, titleFor } from "../titles";
import type { CrumbInput, RouteId } from "../contracts";

const input = (routeId: RouteId, extra: Partial<CrumbInput> = {}, search = ""): CrumbInput => ({
  routeId, ws: "ml-repo", app: "ml_app", appTag: "ml_app",
  params: {}, search: new URLSearchParams(search), ...extra,
});

describe("titleFor", () => {
  it.each<[RouteId, Partial<CrumbInput>, string, string]>([
    ["home", {}, "", "workspaces — vmn-exp"],
    ["apps", {}, "", "ml-repo — vmn-exp"],
    ["experiments", {}, "", "ml_app experiments · ml-repo — vmn-exp"],
    ["run", { run: { verstr: "v", idx: 54, name: "lr-sweep-3" } }, "", "@54 lr-sweep-3 · ml_app — vmn-exp"],
    ["code-diff", {}, "v=%401&to=latest", "diff @1 → latest · ml_app — vmn-exp"],
    ["compare-runs", {}, "sel=a&sel=b&sel=c", "compare 3 runs · ml_app — vmn-exp"],
    ["overlay", {}, "runs=a,b,c,d", "overlay 4 runs · ml_app — vmn-exp"],
    ["tree", {}, "", "stamp tree · ml_app — vmn-exp"],
    ["tree", {}, "v=0.4.1", "stamp tree 0.4.1 · ml_app — vmn-exp"],
    ["actions", {}, "", "actions · ml_app — vmn-exp"],
    ["models", {}, "", "models · ml-repo — vmn-exp"],
    ["model", { params: { modelName: "resnet" } }, "", "resnet · models — vmn-exp"],
    ["reports", {}, "", "reports · ml-repo — vmn-exp"],
    ["report", { params: { rid: "r1" }, reportTitle: "Q3" }, "", "Q3 · reports — vmn-exp"],
    ["report-edit", { params: { rid: "r1" }, reportTitle: "Q3" }, "", "edit Q3 — vmn-exp"],
    ["tokens", {}, "", "API tokens — vmn-exp"],
    ["not-found", {}, "", "not found — vmn-exp"],
    ["sign-in", {}, "", "sign in — vmn-exp"],
  ])("%s %j %s", (routeId, extra, search, title) => {
    expect(titleFor(input(routeId, extra, search))).toBe(title);
  });

  it("prefixes stuck runs on app routes only", () => {
    expect(titleFor(input("experiments"), { stuck: 2 }))
      .toBe("(2 stuck) ml_app experiments · ml-repo — vmn-exp");
    expect(titleFor(input("actions"), { stuck: 1 })).toBe("(1 stuck) actions · ml_app — vmn-exp");
    expect(titleFor(input("experiments"), { stuck: 0 })).toBe("ml_app experiments · ml-repo — vmn-exp");
    expect(titleFor(input("models"), { stuck: 2 })).toBe("models · ml-repo — vmn-exp");
    expect(titleFor(input("not-found"), { stuck: 2 })).toBe("not found — vmn-exp");
  });

  it("a report without a loaded title uses its rid", () => {
    expect(titleFor(input("report", { params: { rid: "r1" } }))).toBe("r1 · reports — vmn-exp");
  });

  it("drops the scope it does not know", () => {
    expect(titleFor(input("apps", { ws: undefined }))).toBe("apps — vmn-exp");
    expect(titleFor(input("models", { ws: undefined }))).toBe("models — vmn-exp");
  });
});

describe("subjectFor", () => {
  it("is the title's leaf without scope, stuck prefix or suffix", () => {
    expect(subjectFor(input("experiments"))).toBe("ml_app experiments");
    expect(subjectFor(input("model", { params: { modelName: "resnet" } }))).toBe("resnet");
  });

  it("keeps a run name that contains the scope separator", () => {
    expect(subjectFor(input("run", { run: { verstr: "v", idx: 54, name: "lr · warm" } }))).toBe("@54 lr · warm");
  });
});
