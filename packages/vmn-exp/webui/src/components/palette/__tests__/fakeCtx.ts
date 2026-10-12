/** A ShellContext for palette tests, without a router or a server. */
import type { ShellContext } from "../../../shell/contracts";

export function fakeCtx(over: Partial<ShellContext> & { ws?: string; app?: string } = {}): ShellContext {
  const ws = "ws" in over ? over.ws : "w";
  const app = "app" in over ? over.app : "app";
  const appTag = app?.replaceAll("/", "-");
  return {
    ws, workspace: ws ? { name: ws, kind: "git" } : undefined,
    workspaces: ws ? [{ name: ws, kind: "git" }] : [],
    isGit: true, meta: { version: "1.0.0" }, metaStatus: "ok", metaError: false,
    authEnabled: false, role: null, readOnly: false, readOnlyReason: null, canAdmin: true,
    routeId: app ? "experiments" : "apps", params: {}, search: new URLSearchParams(),
    pathname: "/", wsFromUrl: Boolean(ws), appTag, app,
    appBase: ws && appTag ? `/ws/${ws}/app/${appTag}` : undefined,
    override: null,
    ...over,
  };
}
