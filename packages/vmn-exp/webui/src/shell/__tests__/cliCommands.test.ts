import { describe, it, expect } from "vitest";
import { cliFor, shellQuote } from "../cliCommands";
import type { CrumbInput, RouteId } from "../contracts";

const input = (routeId: RouteId, extra: Partial<CrumbInput> = {}, search = ""): CrumbInput => ({
  routeId, ws: "ml-repo", app: "ml_app", appTag: "ml_app",
  params: {}, search: new URLSearchParams(search), ...extra,
});
const commands = (i: CrumbInput) => cliFor(i).map((c) => c.command);
const RUN = { verstr: "0.4.1-dev.abc123", idx: 54, name: "lr" };

describe("shellQuote", () => {
  it("leaves safe arguments bare", () => {
    expect(shellQuote("root/svc_1.2@3+x:y=z-w")).toBe("root/svc_1.2@3+x:y=z-w");
  });
  it("single-quotes anything else and escapes quotes", () => {
    expect(shellQuote("lr > 1")).toBe("'lr > 1'");
    expect(shellQuote("it's")).toBe("'it'\\''s'");
    expect(shellQuote("")).toBe("''");
  });
});

describe("cliFor", () => {
  it("experiments lists the app, with the query and archived flag", () => {
    expect(commands(input("experiments"))).toEqual(["vmn-exp list ml_app"]);
    expect(commands(input("experiments", {}, "q=metrics.loss%20%3C%200.1&archived=1")))
      .toEqual(["vmn-exp list ml_app --query 'metrics.loss < 0.1' --archived"]);
  });

  it("run commands use the verstr, never the @N ref", () => {
    expect(commands(input("run", { run: RUN, params: { verstr: "@54" } }))).toEqual([
      "vmn-exp show ml_app -v 0.4.1-dev.abc123",
      "vmn-exp restore ml_app -v 0.4.1-dev.abc123",
      "vmn-exp rerun ml_app -v 0.4.1-dev.abc123",
      "vmn goto -v 0.4.1-dev.abc123 ml_app",
    ]);
    expect(cliFor(input("run", { run: RUN })).map((c) => c.label))
      .toEqual(["show", "restore", "rerun", "goto"]);
  });

  it("run falls back to the URL verstr without a label", () => {
    expect(commands(input("run", { params: { verstr: "0.4.1-dev.x" } }))[0])
      .toBe("vmn-exp show ml_app -v 0.4.1-dev.x");
  });

  it("code diff copies its URL refs verbatim", () => {
    expect(commands(input("code-diff", {}, "v=%403&to=latest")))
      .toEqual(["vmn-exp diff ml_app -v @3 -v latest"]);
  });

  it("compare names every selected run", () => {
    expect(commands(input("compare-runs", {}, "sel=a&sel=b&sel=c")))
      .toEqual(["vmn-exp compare ml_app -v a -v b -v c"]);
  });

  it("compare names each selected run once and skips blanks", () => {
    expect(commands(input("compare-runs", {}, "sel=a&sel=a&sel=&sel=b")))
      .toEqual(["vmn-exp compare ml_app -v a -v b"]);
  });

  it("tree shows the app, or goes to the selected version", () => {
    expect(commands(input("tree"))).toEqual(["vmn show ml_app"]);
    expect(commands(input("tree", {}, "v=0.4.1"))).toEqual(["vmn goto -v 0.4.1 ml_app"]);
  });

  it("models", () => {
    expect(commands(input("models"))).toEqual(["vmn-exp model list"]);
    expect(commands(input("model", { params: { modelName: "resnet" } })))
      .toEqual(["vmn-exp model show resnet"]);
  });

  it("appends --store to vmn-exp commands only", () => {
    expect(commands(input("run", { storeUri: "s3://team-exp/ml", run: RUN }))).toEqual([
      "vmn-exp show ml_app -v 0.4.1-dev.abc123 --store s3://team-exp/ml",
      "vmn-exp restore ml_app -v 0.4.1-dev.abc123 --store s3://team-exp/ml",
      "vmn-exp rerun ml_app -v 0.4.1-dev.abc123 --store s3://team-exp/ml",
      "vmn goto -v 0.4.1-dev.abc123 ml_app",
    ]);
    expect(commands(input("models", { storeUri: "s3://a b" })))
      .toEqual(["vmn-exp model list --store 's3://a b'"]);
  });

  it("app names are in name form", () => {
    expect(commands(input("experiments", { app: "root/svc", appTag: "root-svc" })))
      .toEqual(["vmn-exp list root/svc"]);
  });

  it.each<RouteId>([
    "home", "apps", "overlay", "actions", "reports", "report", "report-edit", "tokens", "not-found", "sign-in",
  ])("%s has no command", (routeId) => {
    expect(cliFor(input(routeId, {}, "runs=a,b"))).toEqual([]);
  });
});
