import { describe, it, expect } from "vitest";
import type { RouteId, ShellContext } from "../contracts";
import type { Workspace } from "../../types";
import { navModel, type NavGroup, type NavItem } from "../navModel";

const GIT: Workspace = { name: "ml-repo", kind: "git", path: "/srv/ml-repo" };
const STORE: Workspace = { name: "team", kind: "store", store: "s3://team/ml" };

function ctx(over: Partial<ShellContext> = {}): ShellContext {
  const workspace = "workspace" in over ? over.workspace : GIT;
  const ws = "ws" in over ? over.ws : workspace?.name;
  const appTag = "appTag" in over ? over.appTag : "ml_app";
  return {
    workspaces: [GIT, STORE],
    metaStatus: "ok", authEnabled: false, role: null,
    readOnly: false, readOnlyReason: null, canAdmin: true, canAttach: true,
    routeId: "experiments", params: {}, search: new URLSearchParams(), pathname: "/",
    wsFromUrl: true, override: null,
    meta: { version: "0.10.2" },
    ...over,
    isGit: workspace?.kind !== "store",
    ws, workspace, appTag,
    app: appTag ? appTag.replaceAll("-", "/") : undefined,
    appBase: ws && appTag ? `/ws/${ws}/app/${appTag}` : undefined,
  };
}

const items = (groups: NavGroup[]): NavItem[] => groups.flatMap((g) => g.items);
const item = (groups: NavGroup[], id: string) => items(groups).find((i) => i.id === id)!;
const ALL_ROUTES: RouteId[] = [
  "home", "tokens", "apps", "experiments", "run", "code-diff", "compare-runs", "overlay",
  "tree", "actions", "models", "model", "reports", "report", "report-edit", "not-found", "sign-in",
];

describe("navModel", () => {
  it("keeps the same groups and items in the same order on every route", () => {
    for (const routeId of ALL_ROUTES) {
      const groups = navModel(ctx({ routeId }));
      expect(groups.map((g) => g.label)).toEqual(["App", "Workspace"]);
      expect(items(groups).map((i) => i.label)).toEqual(
        ["Experiments", "Stamp tree", "Actions", "Apps", "Models", "Reports"],
      );
    }
  });

  it("links every item to its page in the current workspace and app", () => {
    const g = navModel(ctx());
    expect(items(g).map((i) => i.to)).toEqual([
      "/ws/ml-repo/app/ml_app", "/ws/ml-repo/app/ml_app/tree", "/ws/ml-repo/app/ml_app/actions",
      "/ws/ml-repo", "/ws/ml-repo/models", "/ws/ml-repo/reports",
    ]);
    expect(items(g).every((i) => i.disabled === undefined)).toBe(true);
  });

  it("gives each item a distinct icon", () => {
    const g = navModel(ctx({ meta: { version: "1", control_plane: true } }));
    const icons = items(g).map((i) => i.icon);
    expect(icons).toEqual(["experiments", "tree", "actions", "apps", "models", "reports", "key"]);
  });

  it.each<[RouteId, string]>([
    ["experiments", "experiments"], ["run", "experiments"], ["code-diff", "experiments"],
    ["compare-runs", "experiments"], ["overlay", "experiments"], ["tree", "tree"],
    ["actions", "actions"], ["apps", "apps"], ["models", "models"], ["model", "models"],
    ["reports", "reports"], ["report", "reports"], ["report-edit", "reports"],
  ])("marks %s as the %s item", (routeId, active) => {
    const g = navModel(ctx({ routeId }));
    expect(items(g).filter((i) => i.active).map((i) => i.id)).toEqual([active]);
  });

  it.each<RouteId>(["home", "not-found", "sign-in"])("marks nothing active on %s", (routeId) => {
    expect(items(navModel(ctx({ routeId }))).some((i) => i.active)).toBe(false);
  });

  it("disables the app items with no app in context, keeping the workspace items", () => {
    const g = navModel(ctx({ appTag: undefined, routeId: "apps" }));
    for (const id of ["experiments", "tree", "actions"]) {
      expect(item(g, id).disabled).toBe("choose an app first");
      expect(item(g, id).to).toBeUndefined();
    }
    expect(item(g, "models").disabled).toBeUndefined();
  });

  it("disables everything with no workspace", () => {
    const g = navModel(ctx({ ws: undefined, workspace: undefined, appTag: undefined, routeId: "home" }));
    for (const id of ["experiments", "tree", "actions"]) expect(item(g, id).disabled).toBe("choose an app first");
    for (const id of ["apps", "models", "reports"]) {
      expect(item(g, id).disabled).toBe("choose a workspace first");
      expect(item(g, id).to).toBeUndefined();
    }
  });

  it("disables Stamp tree and Actions on a store workspace", () => {
    const g = navModel(ctx({ workspace: STORE }));
    expect(item(g, "tree").disabled).toBe("store workspace: no checkout");
    expect(item(g, "actions").disabled).toBe("store workspace: no checkout");
    expect(item(g, "experiments").disabled).toBeUndefined();
  });

  it("says store over choose-an-app: picking an app would not enable it", () => {
    const g = navModel(ctx({ workspace: STORE, appTag: undefined }));
    expect(item(g, "tree").disabled).toBe("store workspace: no checkout");
  });

  it("disables Actions with the page scope's own read-only reason", () => {
    const reason = "Started with --read-only: actions and edits are off";
    const g = navModel(ctx({ meta: { version: "1", read_only: true }, readOnly: true, readOnlyReason: reason }));
    expect(item(g, "actions").disabled).toBe(reason);
    expect(item(g, "tree").disabled).toBeUndefined();
  });

  it("disables Actions for a viewer or a principal with no role, in the scope's wording", () => {
    const viewer = "Your role in ml-repo is viewer";
    const g = navModel(ctx({ authEnabled: true, role: "viewer", readOnly: true, readOnlyReason: viewer }));
    expect(item(g, "actions").disabled).toBe(viewer);
    const none = "You have no role in ml-repo";
    expect(item(navModel(ctx({ readOnly: true, readOnlyReason: none })), "actions").disabled).toBe(none);
  });

  it("says store over any read-only reason in a store workspace", () => {
    const g = navModel(ctx({ workspace: STORE, readOnly: true, readOnlyReason: "This store gives no edit access" }));
    expect(item(g, "actions").disabled).toBe("store workspace: no checkout");
  });

  it("enables Actions when the scope has no read-only reason", () => {
    expect(item(navModel(ctx({ role: null })), "actions").disabled).toBeUndefined();
  });

  it("shows API tokens only with a control plane and a global admin", () => {
    const cp = { version: "1", control_plane: true };
    const shown = navModel(ctx({ meta: cp }));
    expect(shown.map((g) => g.label)).toEqual(["App", "Workspace", "Server"]);
    expect(item(shown, "tokens")).toMatchObject({ label: "API tokens", to: "/tokens", icon: "key" });

    const admin = navModel(ctx({ meta: { ...cp, role: "admin" }, authEnabled: true, role: "admin", canAdmin: true }));
    expect(item(admin, "tokens")).toBeDefined();
  });

  it("hides API tokens from a per-workspace admin and without a control plane", () => {
    const perWs = navModel(ctx({
      meta: { version: "1", control_plane: true, role: null }, authEnabled: true, role: "admin", canAdmin: false,
    }));
    expect(perWs.map((g) => g.label)).toEqual(["App", "Workspace"]);
    expect(navModel(ctx({ meta: { version: "1" } })).map((g) => g.label)).toEqual(["App", "Workspace"]);
  });

  it("marks API tokens active on /tokens", () => {
    const g = navModel(ctx({ routeId: "tokens", meta: { version: "1", control_plane: true } }));
    expect(items(g).filter((i) => i.active).map((i) => i.id)).toEqual(["tokens"]);
  });
});
