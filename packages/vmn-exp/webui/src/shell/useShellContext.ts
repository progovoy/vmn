/** Everything a shell component knows about the current route. Shell only:
 *  it reads router matches, which throw outside a data router, so pages use
 *  usePageScope instead. */
import { useEffect, useMemo } from "react";
import { useLocation, useMatches } from "react-router-dom";
import { appName } from "../api";
import { appHref } from "../util";
import type { RouteHandle, ShellContext } from "./contracts";
import { lastWorkspace, rememberWorkspace } from "./lastWorkspace";
import { useShellOverride } from "./shellOverride";
import { usePageScope } from "./usePageScope";

export function useShellContext(): ShellContext {
  const matches = useMatches();
  const deepest = matches[matches.length - 1];
  const handle = deepest?.handle as RouteHandle | undefined;
  const params = (deepest?.params ?? {}) as Record<string, string | undefined>;
  const location = useLocation();
  const override = useShellOverride();

  const wsFromUrl = params.ws !== undefined;
  // An unknown :ws stays set (NotFound names it); only a known one is remembered.
  const ws = params.ws ?? lastWorkspace() ?? undefined;
  const scope = usePageScope(ws);
  const known = Boolean(scope.workspace);
  useEffect(() => {
    if (wsFromUrl && ws && known) rememberWorkspace(ws);
  }, [wsFromUrl, ws, known]);

  const search = useMemo(() => new URLSearchParams(location.search), [location.search]);
  const appTag = params.app;
  const app = appTag ? appName(appTag) : undefined;
  return {
    ...scope,
    routeId: handle?.id ?? "not-found",
    params, search,
    pathname: location.pathname,
    wsFromUrl,
    appTag,
    app,
    appBase: ws && app ? appHref(ws, app) : undefined,
    wide: Boolean(handle?.wide),
    override,
  };
}
