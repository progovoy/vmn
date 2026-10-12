/** Shared fixtures for the topbar tests: a ShellContext and a data router. */
import { render } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import type { ReactNode } from "react";
import { createQueryClient } from "../../../queryClient";
import type { ShellContext } from "../../../shell/contracts";
import type { Workspace } from "../../../types";

export const ML_REPO: Workspace = { name: "ml-repo", kind: "git", path: "/srv/ml-repo" };
export const TEAM: Workspace = {
  name: "team", kind: "store", store: "s3://team-exp/ml/a/very/long/prefix/for/the/runs",
};

export function ctxOf(over: Partial<ShellContext> = {}): ShellContext {
  return {
    routeId: "experiments", params: {}, search: new URLSearchParams(), pathname: "/",
    wsFromUrl: true, override: null,
    workspaces: [ML_REPO, TEAM], isGit: true,
    metaStatus: "ok", metaError: false, authEnabled: false, role: null,
    readOnly: false, readOnlyReason: null, canAdmin: true,
    meta: { version: "0.10.2" },
    ...over,
  };
}

/** Renders *ui* under a data router whose only route has handle `{id}`. */
export function renderShell(ui: ReactNode) {
  const router = createMemoryRouter(
    [{ path: "*", element: ui, handle: { id: "experiments" } }], { initialEntries: ["/"] },
  );
  return render(
    <QueryClientProvider client={createQueryClient()}><RouterProvider router={router} /></QueryClientProvider>,
  );
}
