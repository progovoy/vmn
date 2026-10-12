import { describe, it, expect } from "vitest";
import { completeCli, isRef, parseCliQuery, type ParseScope } from "../parseCliQuery";

const scope: ParseScope = { apps: ["ml_app", "root/svc"], workspaces: ["w", "prod"], app: "ml_app" };
const noApp: ParseScope = { ...scope, app: undefined };
const parse = (text: string, s: ParseScope = scope) => parseCliQuery(text, s);

describe("isRef", () => {
  it.each(["@3", "@54", "latest", "@latest", "0.2.0", "abc1", "0.2.0-dev.1+a"])("%s is a ref", (t) =>
    expect(isRef(t)).toBe(true));
  it.each(["@", "abc", "ab1", "abcd", "a b1", "@x"])("%s is not", (t) => expect(isRef(t)).toBe(false));
});

describe("parseCliQuery: show", () => {
  it.each([
    ["@54", "@54"],
    ["latest", "latest"],
    ["@latest", "latest"],
    ["show @54", "@54"],
    ["show -v @54", "@54"],
    ["show --version 0.2.0", "0.2.0"],
    ["show ml_app -v @54", "@54"],
    ["vmn-exp show ml_app -v @54", "@54"],
    ["vmn exp show -v @54 ml_app", "@54"],
  ])("%s", (text, ref) => {
    expect(parse(text)).toEqual({ kind: "show", app: "ml_app", ref });
  });

  it("sets the app from a positional name or its tag form", () => {
    expect(parse("show root/svc -v @2")).toEqual({ kind: "show", app: "root/svc", ref: "@2" });
    expect(parse("show root-svc @2")).toEqual({ kind: "show", app: "root/svc", ref: "@2" });
  });

  it("falls back to the workspace's only app, else asks for one", () => {
    expect(parse("@3", { ...noApp, apps: ["solo"] })).toEqual({ kind: "show", app: "solo", ref: "@3" });
    expect(parse("@3", noApp)).toEqual({ kind: "error", message: "name an app: show <app> -v <ref>" });
  });

  it("asks for a run when none is named", () => {
    expect(parse("show")).toEqual({ kind: "error", message: "name a run: show <app> -v <ref>" });
  });

  it("names a token that is neither an app nor a ref", () => {
    expect(parse("show ml_ap")).toEqual({ kind: "error", message: "no app or run named ml_ap" });
  });
});

describe("parseCliQuery: list", () => {
  it.each([
    ["list metrics.loss < 0.3", "metrics.loss < 0.3", false],
    ["list ml_app --query 'metrics.loss < 0.3'", "metrics.loss < 0.3", false],
    ["q note ~ \"abc\"", 'note ~ "abc"', false],
    ["list --archived", "", true],
    ["list", "", false],
    ["metrics.loss < 0.3", "metrics.loss < 0.3", false],
    ["params.lr = 0.1", "params.lr = 0.1", false],
    ["branch = main", "branch = main", false],
    ["status in (\"failed\")", 'status in ("failed")', false],
  ])("%s", (text, query, archived) => {
    expect(parse(text)).toEqual({ kind: "list", app: "ml_app", query, archived });
  });

  it("takes the app only before the expression, never from inside it", () => {
    expect(parse("q params.app = ml_app", noApp)).toEqual({ kind: "error", message: "name an app: list <app> <query>" });
    expect(parse("list ml_app params.app = root/svc"))
      .toEqual({ kind: "list", app: "ml_app", query: "params.app = root/svc", archived: false });
    expect(parse("list root/svc params.app = ml_app"))
      .toEqual({ kind: "list", app: "root/svc", query: "params.app = ml_app", archived: false });
  });
});

describe("parseCliQuery: compare, diff, overlay", () => {
  it("collects positional and -v refs for compare", () => {
    expect(parse("compare @3 @7 0.2.0")).toEqual({ kind: "compare", app: "ml_app", refs: ["@3", "@7", "0.2.0"] });
    expect(parse("compare -v @3 -v @7")).toEqual({ kind: "compare", app: "ml_app", refs: ["@3", "@7"] });
  });

  it("needs 2 to 50 runs to compare", () => {
    expect(parse("compare @3")).toEqual({ kind: "error", message: "compare needs at least 2 runs" });
    const many = Array.from({ length: 51 }, (_, i) => `@${i + 1}`).join(" ");
    expect(parse(`compare ${many}`)).toEqual({ kind: "error", message: "compare takes at most 50 runs" });
  });

  it.each([
    ["diff @1 @2", "@1", "@2"],
    ["diff -v @1 -v @2", "@1", "@2"],
    ["diff -v @1 --to latest", "@1", "latest"],
    ["diff @1", "@1", undefined],
  ])("%s", (text, from, to) => {
    expect(parse(text)).toEqual({ kind: "diff", app: "ml_app", from, to });
  });

  it("asks diff for a run", () => {
    expect(parse("diff")).toEqual({ kind: "error", message: "name a run: diff <app> <ref> <ref>" });
  });

  it("overlays any number of runs", () => {
    expect(parse("overlay ml_app @1 @2 @3")).toEqual({ kind: "overlay", app: "ml_app", refs: ["@1", "@2", "@3"] });
    expect(parse("overlay")).toEqual({ kind: "error", message: "overlay needs at least 1 run" });
  });
});

describe("parseCliQuery: goto, tree, restore, rerun", () => {
  it.each([
    ["goto 1.2", "1.2"],
    ["goto -v 1.2.0 ml_app", "1.2.0"],
    ["vmn goto -v 1.2.0 ml_app", "1.2.0"],
    ["goto", undefined],
  ])("%s", (text, version) => {
    expect(parse(text)).toEqual({ kind: "goto", app: "ml_app", version });
  });

  it("opens the tree, at a version when given", () => {
    expect(parse("tree")).toEqual({ kind: "tree", app: "ml_app", version: undefined });
    expect(parse("tree 1.2.0")).toEqual({ kind: "tree", app: "ml_app", version: "1.2.0" });
  });

  it("copies restore and rerun commands", () => {
    expect(parse("restore @3")).toEqual({ kind: "copy", app: "ml_app", verb: "restore", ref: "@3" });
    expect(parse("rerun -v 0.2.0")).toEqual({ kind: "copy", app: "ml_app", verb: "rerun", ref: "0.2.0" });
    expect(parse("restore")).toEqual({ kind: "error", message: "name a run: restore <app> -v <ref>" });
  });
});

describe("parseCliQuery: status, create, pages, apps, workspaces", () => {
  it("filters by a status word", () => {
    expect(parse("status stuck")).toEqual({ kind: "status", app: "ml_app", status: "stuck" });
    expect(parse("status nope")).toEqual({
      kind: "error", message: "status is one of running, stuck, failed, succeeded, created",
    });
  });

  it("creates", () => {
    expect(parse("create")).toEqual({ kind: "create", app: "ml_app" });
    expect(parse("new")).toEqual({ kind: "create", app: "ml_app" });
  });

  it.each([
    ["models", { kind: "page", page: "models" }],
    ["model resnet@3", { kind: "page", page: "model", model: "resnet" }],
    ["model resnet", { kind: "page", page: "model", model: "resnet" }],
    ["reports", { kind: "page", page: "reports" }],
    ["tokens", { kind: "page", page: "tokens" }],
    ["docs", { kind: "page", page: "docs" }],
    ["apps", { kind: "page", page: "apps" }],
    ["actions", { kind: "page", page: "actions", app: "ml_app" }],
    ["experiments", { kind: "page", page: "experiments", app: "ml_app" }],
    ["runs", { kind: "page", page: "experiments", app: "ml_app" }],
    ["actions root/svc", { kind: "page", page: "actions", app: "root/svc" }],
  ])("%s", (text, want) => {
    expect(parse(text)).toEqual(want);
  });

  it("app pages need an app", () => {
    expect(parse("actions", noApp)).toEqual({ kind: "error", message: "name an app: actions <app>" });
  });

  it("jumps to an app or a workspace", () => {
    expect(parse("app root-svc")).toEqual({ kind: "app", app: "root/svc" });
    expect(parse("root/svc")).toEqual({ kind: "app", app: "root/svc" });
    expect(parse("ws prod")).toEqual({ kind: "ws", ws: "prod" });
    expect(parse("prod")).toEqual({ kind: "ws", ws: "prod" });
    expect(parse("app nope")).toEqual({ kind: "error", message: "no app named nope" });
    expect(parse("ws nope")).toEqual({ kind: "error", message: "no workspace named nope" });
  });

  it("leaves anything else to the fuzzy search", () => {
    expect(parse("")).toEqual({ kind: "none" });
    expect(parse("lr-sweep")).toEqual({ kind: "none" });
    expect(parse("0.2.0.dev9")).toEqual({ kind: "none" });
  });
});

describe("completeCli", () => {
  it("completes the verb, then the app", () => {
    expect(completeCli("sh", ["ml_app"])).toBe("show ");
    expect(completeCli("show ml_", ["ml_app"])).toBe("show ml_app ");
    expect(completeCli("vmn-exp comp", ["ml_app"])).toBe("vmn-exp compare ");
  });

  it("completes a bare app as the first word too", () => {
    expect(completeCli("ml_", ["ml_app"])).toBe("ml_app ");
    expect(completeCli("root-", ["root/svc"])).toBe("root-svc ");
  });

  it("returns null with nothing to complete", () => {
    expect(completeCli("show @3", ["ml_app"])).toBeNull();
    expect(completeCli("", ["ml_app"])).toBeNull();
  });
});
