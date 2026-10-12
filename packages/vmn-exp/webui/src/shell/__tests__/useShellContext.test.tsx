import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, Outlet, RouterProvider } from "react-router-dom";
import { createQueryClient } from "../../queryClient";
import type { Meta, Workspace } from "../../types";
import type { ShellContext } from "../contracts";

const meta = vi.fn<() => Promise<Meta>>();
const workspaces = vi.fn<() => Promise<Workspace[]>>();
vi.mock("../../api", () => ({
  api: { meta: () => meta(), workspaces: () => workspaces() },
  appName: (tag: string) => tag.replaceAll("-", "/"),
}));

import { useShellContext } from "../useShellContext";
import { lastWorkspace, rememberWorkspace } from "../lastWorkspace";
import { ShellOverrideProvider, useOverrideRoute } from "../shellOverride";

let seen: ShellContext | undefined;
function Probe() {
  seen = useShellContext();
  return <span data-testid="ctx">{`${seen.routeId}|${seen.ws ?? "-"}|${seen.override ?? "-"}`}</span>;
}
function Overrides() {
  useOverrideRoute("not-found");
  return null;
}

function renderAt(path: string) {
  const router = createMemoryRouter(
    [{
      path: "/",
      element: <ShellOverrideProvider><Probe /><Outlet /></ShellOverrideProvider>,
      children: [
        { path: "tokens", element: null, handle: { id: "tokens" } },
        { path: "ws/:ws", element: null, handle: { id: "apps" } },
        { path: "ws/:ws/app/:app", element: null, handle: { id: "experiments" } },
        { path: "ws/:ws/app/:app/overlay", element: null, handle: { id: "overlay", wide: true } },
        { path: "ws/:ws/missing", element: <Overrides />, handle: { id: "apps" } },
        { path: "bare", element: null },
      ],
    }],
    { initialEntries: [path] },
  );
  render(
    <QueryClientProvider client={createQueryClient()}><RouterProvider router={router} /></QueryClientProvider>,
  );
}

describe("useShellContext", () => {
  beforeEach(() => {
    sessionStorage.clear();
    seen = undefined;
    meta.mockResolvedValue({ version: "0.10.2" });
    workspaces.mockResolvedValue([{ name: "ml-repo", kind: "git" }, { name: "team", kind: "store" }]);
  });

  it("reads the route id, params and app from the deepest match", async () => {
    renderAt("/ws/ml-repo/app/root-svc?q=lr%3E1");
    await waitFor(() => expect(seen?.workspace?.name).toBe("ml-repo"));
    expect(seen).toMatchObject({
      routeId: "experiments", ws: "ml-repo", wsFromUrl: true, appTag: "root-svc", app: "root/svc",
      appBase: "/ws/ml-repo/app/root-svc", pathname: "/ws/ml-repo/app/root-svc", override: null,
    });
    expect(seen!.params.app).toBe("root-svc");
    expect(seen!.search.get("q")).toBe("lr>1");
  });

  it("says whether the deepest route asks for the full content width", async () => {
    renderAt("/ws/ml-repo/app/root-svc/overlay");
    await waitFor(() => expect(seen?.workspace?.name).toBe("ml-repo"));
    expect(seen!.wide).toBe(true);
  });

  it("is not wide on a route without the flag", async () => {
    renderAt("/ws/ml-repo/app/root-svc");
    await waitFor(() => expect(seen?.workspace?.name).toBe("ml-repo"));
    expect(seen!.wide).toBe(false);
  });

  it("remembers a known workspace from the URL", async () => {
    renderAt("/ws/team");
    await waitFor(() => expect(lastWorkspace()).toBe("team"));
  });

  it("uses the last workspace on a global route", async () => {
    rememberWorkspace("ml-repo");
    renderAt("/tokens");
    await waitFor(() => expect(seen?.workspace?.name).toBe("ml-repo"));
    expect(seen).toMatchObject({ routeId: "tokens", ws: "ml-repo", wsFromUrl: false });
    expect(seen!.appTag).toBeUndefined();
    expect(seen!.appBase).toBeUndefined();
  });

  it("keeps an unknown workspace's name without a workspace, and does not remember it", async () => {
    rememberWorkspace("ml-repo");
    renderAt("/ws/bogus");
    await waitFor(() => expect(workspaces).toHaveBeenCalled());
    await waitFor(() => expect(seen?.workspaces.length).toBe(2));
    expect(seen!.ws).toBe("bogus");
    expect(seen!.workspace).toBeUndefined();
    expect(lastWorkspace()).toBe("ml-repo");
  });

  it("defaults the route id to not-found when the route has no handle", async () => {
    renderAt("/bare");
    expect(await screen.findByTestId("ctx")).toHaveTextContent(/^not-found\|/);
  });

  it("follows useOverrideRoute", async () => {
    renderAt("/ws/ml-repo/missing");
    await waitFor(() => expect(screen.getByTestId("ctx")).toHaveTextContent("apps|ml-repo|not-found"));
  });
});
