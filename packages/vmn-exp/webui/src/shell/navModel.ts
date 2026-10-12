/** The sidebar's groups and items (plan 19 §1.2). Items never move between
 *  routes: one that does not apply is disabled with a reason, not removed. */
import type { IconName } from "../components/shell/icons";
import type { RouteId, ShellContext } from "./contracts";

export type NavId = "experiments" | "tree" | "actions" | "apps" | "models" | "reports" | "tokens";

export interface NavItem {
  id: NavId; label: string; icon: IconName;
  /** Absent when disabled. */
  to?: string;
  /** Why the item does not apply here (its `title`). */
  disabled?: string;
  active: boolean;
}
export interface NavGroup { id: "app" | "workspace" | "server"; label: string; items: NavItem[] }

const ACTIVE: Partial<Record<RouteId, NavId>> = {
  experiments: "experiments", run: "experiments", "code-diff": "experiments",
  "compare-runs": "experiments", overlay: "experiments",
  tree: "tree", actions: "actions", apps: "apps",
  models: "models", model: "models",
  reports: "reports", report: "reports", "report-edit": "reports",
  tokens: "tokens",
};

const NO_APP = "choose an app first";
const NO_WS = "choose a workspace first";
const STORE = "store workspace: no checkout";

/** Why Actions cannot run here (the page scope's own read-only wording);
 *  permanent reasons first, so picking an app is never suggested as the fix
 *  for a store or a read-only server. */
const actionsBlocked = (ctx: ShellContext): string | undefined =>
  ctx.isGit ? ctx.readOnlyReason ?? undefined : STORE;

export function navModel(ctx: ShellContext): NavGroup[] {
  const active = ACTIVE[ctx.routeId];
  const item = (
    id: NavId, label: string, icon: IconName, to: string | undefined, missing: string, blocked?: string,
  ): NavItem => {
    const disabled = blocked ?? (to === undefined ? missing : undefined);
    return { id, label, icon, to: disabled ? undefined : to, disabled, active: active === id };
  };
  const app = ctx.appBase;
  const ws = ctx.ws ? `/ws/${ctx.ws}` : undefined;

  const groups: NavGroup[] = [
    {
      id: "app", label: "App", items: [
        item("experiments", "Experiments", "experiments", app, NO_APP),
        item("tree", "Stamp tree", "tree", app && `${app}/tree`, NO_APP, ctx.isGit ? undefined : STORE),
        item("actions", "Actions", "actions", app && `${app}/actions`, NO_APP, actionsBlocked(ctx)),
      ],
    },
    {
      id: "workspace", label: "Workspace", items: [
        item("apps", "Apps", "apps", ws, NO_WS),
        item("models", "Models", "models", ws && `${ws}/models`, NO_WS),
        item("reports", "Reports", "reports", ws && `${ws}/reports`, NO_WS),
      ],
    },
  ];
  if (ctx.meta?.control_plane && ctx.canAdmin) {
    groups.push({ id: "server", label: "Server", items: [item("tokens", "API tokens", "key", "/tokens", "")] });
  }
  return groups;
}
