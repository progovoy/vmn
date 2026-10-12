import { describe, it, expect } from "vitest";
import { isMissingRun, notFoundCopy, plain, type NotFoundFacts } from "../notFoundCopy";
import type { NotFoundProps } from "../contracts";

const FACTS: NotFoundFacts = { workspaces: ["ml-repo", "team"] };

function copy(props: NotFoundProps, facts: Partial<NotFoundFacts> = {}) {
  const c = notFoundCopy(props, { ...FACTS, ...facts });
  return {
    ...c,
    h1: plain(c.h1),
    body: c.body.map(plain),
    actions: c.actions.map((a) => [plain(a.label), a.to]),
  };
}

describe("notFoundCopy: route", () => {
  it("names the address and offers every workspace", () => {
    const c = copy({ kind: "route", pathname: "/nowhere" });
    expect(c.h1).toBe("No page at this address");
    expect(c.body).toEqual(["/nowhere isn't a vmn-exp ui page."]);
    expect(c.actions).toEqual([["All workspaces", "/"]]);
    expect(c.hint).toBe("⌘K jumps to any run, app or page.");
  });

  it("offers the workspace the address names, when it exists", () => {
    expect(copy({ kind: "route", pathname: "/ws/ml-repo/bogus" }).actions)
      .toEqual([["All workspaces", "/"], ["Open ml-repo", "/ws/ml-repo"]]);
    expect(copy({ kind: "route", pathname: "/ws/nope/bogus" }).actions)
      .toEqual([["All workspaces", "/"]]);
  });

  it("puts the pathname in mono", () => {
    const c = notFoundCopy({ kind: "route", pathname: "/x" }, FACTS);
    expect(c.body[0][0]).toEqual({ mono: "/x" });
  });
});

describe("notFoundCopy: workspace", () => {
  it("lists the workspaces as links and suggests the nearest", () => {
    const c = copy({ kind: "workspace", ws: "ml-rpo" });
    expect(c.h1).toBe("No workspace named ml-rpo");
    expect(c.body).toEqual(["Workspaces on this server: ml-repo, team.", "Did you mean ml-repo?"]);
    const raw = notFoundCopy({ kind: "workspace", ws: "ml-rpo" }, FACTS);
    expect(raw.body[0]).toContainEqual({ mono: "ml-repo", to: "/ws/ml-repo" });
    expect(raw.body[1]).toContainEqual({ mono: "ml-repo", to: "/ws/ml-repo" });
    expect(c.cli).toBe("vmn-exp ui --repo <path>");
  });

  it("lists at most 5 workspaces", () => {
    const names = ["a", "b", "c", "d", "e", "f", "g"];
    expect(copy({ kind: "workspace", ws: "zzzzz" }, { workspaces: names }).body)
      .toEqual(["Workspaces on this server: a, b, c, d, e."]);
  });

  it("says when the server has none", () => {
    expect(copy({ kind: "workspace", ws: "x" }, { workspaces: [] }).body)
      .toEqual(["This server has no workspaces yet."]);
  });

  it("offers to attach a checkout only when allowed", () => {
    expect(copy({ kind: "workspace", ws: "x" }).actions).toEqual([["All workspaces", "/"]]);
    expect(copy({ kind: "workspace", ws: "x" }, { canAttach: true }).actions).toEqual([
      ["All workspaces", "/"], ["Attach a checkout as x", "/?add=1&name=x"],
    ]);
  });
});

describe("notFoundCopy: app", () => {
  const props: NotFoundProps = { kind: "app", ws: "ml-repo", appTag: "ml_ap" };

  it("suggests the nearest app and opens it", () => {
    const c = copy(props, { apps: ["ml_app", "eval"] });
    expect(c.h1).toBe("No app ml_ap in ml-repo");
    expect(c.body).toEqual(["Did you mean ml_app?", "Apps here: ml_app, eval."]);
    expect(c.actions).toEqual([["Open ml_app", "/ws/ml-repo/app/ml_app"]]);
  });

  it("opens the workspace without a suggestion", () => {
    const c = copy(props, { apps: ["zeta"] });
    expect(c.body).toEqual(["Apps here: zeta."]);
    expect(c.actions).toEqual([["Open ml-repo", "/ws/ml-repo"]]);
  });

  it("links a root app's service in tag form", () => {
    const c = copy({ kind: "app", ws: "ml-repo", appTag: "root-svc1" }, { apps: ["root/svc"] });
    expect(c.h1).toBe("No app root/svc1 in ml-repo");
    expect(c.actions).toEqual([["Open root/svc", "/ws/ml-repo/app/root-svc"]]);
  });

  it("explains how an app appears in an empty git workspace", () => {
    expect(copy(props, { apps: [] }).body).toEqual([
      "ml-repo has no apps yet. An app appears after its first vmn stamp -r patch <app> " +
        "or vmn-exp run <app> -- <cmd>.",
    ]);
  });

  it("says an empty store has no runs", () => {
    expect(copy(props, { apps: [], isStore: true }).body).toEqual(["This store has no runs yet."]);
  });

  it("never offers or hints at creating the app", () => {
    const c = copy(props, { apps: [] });
    const all = [c.h1, ...c.body, ...c.actions.map((a) => a[0]), c.hint ?? "", c.cli ?? ""].join(" ");
    expect(all).not.toMatch(/create|new run/i);
  });
});

describe("notFoundCopy: run", () => {
  const at = (ref: string): NotFoundProps => ({ kind: "run", ws: "ml-repo", appTag: "ml_app", runRef: ref });

  it("gives an @N ref the app's range", () => {
    const c = copy(at("@540"), { runTotal: 53 });
    expect(c.h1).toBe("No run @540 in ml_app");
    expect(c.body).toEqual(["ml_app has 53 runs (@1–@53)."]);
    expect(c.actions).toEqual([["Back to experiments", "/ws/ml-repo/app/ml_app"]]);
    expect(c.cli).toBe("vmn-exp list ml_app");
  });

  it("says a single run in the singular", () => {
    expect(copy(at("@2"), { runTotal: 1 }).body).toEqual(["ml_app has 1 run (@1)."]);
  });

  it("keeps the shell command intact for a ref with a single quote", () => {
    const c = copy(at("x'; rm -rf ~; '"));
    expect(c.cli).toBe(`vmn-exp list ml_app --query 'verstr ~ "x; rm -rf ~; "'`);
  });

  it("says an app without runs has none", () => {
    expect(copy(at("@2"), { runTotal: 0 }).body).toEqual(["ml_app has no runs yet."]);
  });

  it("suggests pruning or an unpushed offline run for another ref, and searches for it", () => {
    const c = copy(at("0.2.0.dev3"));
    expect(c.body).toEqual([
      "It may have been pruned (vmn-exp prune), or recorded offline and not pushed yet (vmn-exp push).",
    ]);
    expect(c.actions).toEqual([
      ["Back to experiments", "/ws/ml-repo/app/ml_app"],
      ["Search runs for 0.2.0.dev3",
        `/ws/ml-repo/app/ml_app?q=${encodeURIComponent('verstr ~ "0.2.0.dev3"')}`],
    ]);
    expect(c.cli).toBe(`vmn-exp list ml_app --query 'verstr ~ "0.2.0.dev3"'`);
  });

  it("falls back to the pruned line for an @N ref while the total is unknown", () => {
    expect(copy(at("@9")).body[0]).toMatch(/^It may have been pruned/);
  });
});

describe("notFoundCopy: model, report, control plane, needs-git", () => {
  it("model", () => {
    const c = copy({ kind: "model", ws: "ml-repo", name: "resnet" });
    expect(c.h1).toBe("No model resnet in ml-repo");
    expect(c.body).toEqual(["It may have been deleted (vmn-exp model delete)."]);
    expect(c.actions).toEqual([["All models", "/ws/ml-repo/models"]]);
    expect(c.cli).toBe("vmn-exp model list");
  });

  it("report", () => {
    const c = copy({ kind: "report", ws: "ml-repo", rid: "r_12" });
    expect(c.h1).toBe("No report r_12 in ml-repo");
    expect(c.body).toEqual([]);
    expect(c.actions).toEqual([["All reports", "/ws/ml-repo/reports"]]);
  });

  it("control plane", () => {
    const c = copy({ kind: "control-plane" });
    expect(c.h1).toBe("API tokens need a control plane");
    expect(c.body).toEqual([
      "This server has no control plane. Start it with vmn-exp ui --config server.yml.",
    ]);
    expect(c.actions).toEqual([["All workspaces", "/"]]);
  });

  it("needs-git names the page and the store", () => {
    const props: NotFoundProps = { kind: "needs-git", ws: "team", appTag: "ml_app", page: "tree" };
    const c = copy(props, { storeUri: "s3://team-exp/ml" });
    expect(c.h1).toBe("Stamp tree needs a git workspace");
    expect(c.body).toEqual([
      "team is a store workspace (s3://team-exp/ml). Versions live in git tags: open a git " +
        "workspace of this app, or run vmn show ml_app in a checkout.",
    ]);
    expect(c.actions).toEqual([["Open experiments", "/ws/team/app/ml_app"]]);
    expect(copy({ ...props, page: "actions" }).h1).toBe("Actions need a git workspace");
  });
});

describe("isMissingRun", () => {
  const err = (status: number, detail: string) =>
    Object.assign(new Error(detail), { status, body: { detail } });

  it("is a 404 for an experiment or a 400 for an invalid version", () => {
    expect(isMissingRun(err(404, "Experiment @540 not found"))).toBe(true);
    expect(isMissingRun(err(400, "Invalid version: x"))).toBe(true);
  });

  it("is nothing else", () => {
    expect(isMissingRun(err(404, "Workspace x not found"))).toBe(false);
    expect(isMissingRun(err(400, "bad query"))).toBe(false);
    expect(isMissingRun(err(500, "Experiment boom"))).toBe(false);
    expect(isMissingRun(new Error("network"))).toBe(false);
  });
});
