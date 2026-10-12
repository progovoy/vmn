import { describe, it, expect, vi, beforeAll, afterAll, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, Outlet, RouterProvider } from "react-router-dom";
import type { ReactNode } from "react";
import { createQueryClient } from "../../../queryClient";
import type { AppRow, Meta, Workspace } from "../../../types";
import { DOCS_URL, LAST_WS_KEY, type AppStatus } from "../../../shell/contracts";

const meta = vi.fn<() => Promise<Meta>>();
const workspaces = vi.fn<() => Promise<Workspace[]>>();
const apps = vi.fn<(ws: string) => Promise<AppRow[]>>();
const appStatus = vi.fn<(ws: string, tag: string) => Promise<AppStatus>>();
vi.mock("../../../api", () => ({
  api: { meta: () => meta(), workspaces: () => workspaces(), apps: (ws: string) => apps(ws) },
  appName: (tag: string) => tag.replaceAll("-", "/"),
  appTag: (name: string) => name.replaceAll("/", "-"),
}));
vi.mock("../../../apiShell", () => ({
  apiShell: {
    appStatus: (ws: string, tag: string) => appStatus(ws, tag),
    gitContext: vi.fn(), resolveRef: vi.fn(),
  },
}));

import Sidebar from "../Sidebar";
import { useShellContext } from "../../../shell/useShellContext";

// A data router builds a fetch Request per navigation; Node's Request rejects
// jsdom's AbortSignal, so drop the signal in this environment only.
const NodeRequest = globalThis.Request;
beforeAll(() => {
  globalThis.Request = class extends NodeRequest {
    constructor(input: RequestInfo | URL, init?: RequestInit) {
      super(input, init && { ...init, signal: undefined });
    }
  } as typeof Request;
});
afterAll(() => { globalThis.Request = NodeRequest; });

function Shell({ onNavigate, footExtra }: { onNavigate?: () => void; footExtra?: ReactNode }) {
  const ctx = useShellContext();
  return <><aside><Sidebar ctx={ctx} onNavigate={onNavigate} footExtra={footExtra} /></aside><Outlet /></>;
}

function renderAt(path: string, opts: { onNavigate?: () => void; footExtra?: ReactNode } = {}) {
  const router = createMemoryRouter(
    [{
      path: "/",
      element: <Shell {...opts} />,
      children: [
        { index: true, element: null, handle: { id: "home" } },
        { path: "tokens", element: null, handle: { id: "tokens" } },
        { path: "ws/:ws", element: null, handle: { id: "apps" } },
        { path: "ws/:ws/models", element: null, handle: { id: "models" } },
        { path: "ws/:ws/app/:app", element: null, handle: { id: "experiments" } },
        { path: "ws/:ws/app/:app/tree", element: null, handle: { id: "tree" } },
      ],
    }],
    { initialEntries: [path] },
  );
  render(
    <QueryClientProvider client={createQueryClient()}><RouterProvider router={router} /></QueryClientProvider>,
  );
  return router;
}

const wsSelect = () => screen.getByRole("combobox", { name: "Workspace" }) as HTMLSelectElement;

describe("Sidebar", () => {
  beforeEach(() => {
    sessionStorage.clear();
    meta.mockResolvedValue({ version: "0.10.2", vmn_exp_version: "0.1.4", control_plane: true });
    workspaces.mockResolvedValue([
      { name: "ml-repo", kind: "git", path: "/srv/checkouts/ml-repo" },
      { name: "team", kind: "store", store: "s3://team-exp/ml" },
    ]);
    apps.mockResolvedValue([{ name: "ml_app", experiments: 3, versions: 2 }]);
    appStatus.mockResolvedValue({
      total: 5, counts: { created: 0, running: 1, stuck: 2, succeeded: 2, failed: 0 },
      failed_recent: 0, recent_sec: 86400, rollup: "stuck",
    });
  });

  it("names the workspace select Workspace and shows each option's kind", async () => {
    renderAt("/ws/ml-repo/app/ml_app");
    await waitFor(() => expect(wsSelect().value).toBe("ml-repo"));
    const options = within(wsSelect()).getAllByRole("option").map((o) => o.textContent);
    expect(options).toEqual(["workspace…", "ml-repo — git", "team — store"]);
    expect(await screen.findByText("/srv/checkouts/ml-repo")).toBeInTheDocument();
  });

  it("navigates to the chosen workspace", async () => {
    const router = renderAt("/ws/ml-repo/app/ml_app");
    await waitFor(() => expect(wsSelect().value).toBe("ml-repo"));
    fireEvent.change(wsSelect(), { target: { value: "team" } });
    expect(router.state.location.pathname).toBe("/ws/team");
  });

  it("renders three nav landmarks and one visible Workspace heading", async () => {
    renderAt("/ws/ml-repo/app/ml_app");
    await screen.findByRole("navigation", { name: "Server" });
    expect(screen.getAllByRole("navigation")).toHaveLength(3);
    for (const name of ["App", "Workspace", "Server"]) {
      expect(screen.getByRole("navigation", { name })).toBeInTheDocument();
    }
    expect(screen.getAllByRole("heading", { name: "Workspace" })).toHaveLength(1);
  });

  it("links the vmn-exp wordmark home with state.home", async () => {
    const router = renderAt("/ws/ml-repo/app/ml_app");
    const brand = screen.getByRole("link", { name: "vmn-exp" });
    expect(brand).toHaveAttribute("href", "/");
    fireEvent.click(brand);
    expect(router.state.location.pathname).toBe("/");
    expect(router.state.location.state).toEqual({ home: true });
  });

  it("shows the two versions as separate spans and a labelled docs link", async () => {
    renderAt("/ws/ml-repo");
    const exp = await screen.findByText("vmn-exp 0.1.4");
    const core = screen.getByText("vmn 0.10.2");
    expect(exp.tagName).toBe("SPAN");
    expect(core.tagName).toBe("SPAN");
    expect(exp).not.toBe(core);
    const docs = screen.getByRole("link", { name: "Docs (opens on GitHub)" });
    expect(docs).toHaveAttribute("href", DOCS_URL);
    expect(docs).toHaveAttribute("target", "_blank");
    expect(docs.querySelector("svg")).not.toBeNull();
  });

  it("omits the vmn-exp version when the server has none", async () => {
    meta.mockResolvedValue({ version: "0.10.2", vmn_exp_version: null });
    renderAt("/ws/ml-repo");
    await screen.findByText("vmn 0.10.2");
    expect(screen.queryByText(/^vmn-exp /)).toBeNull();
  });

  it("draws 7 distinct nav icons", async () => {
    renderAt("/ws/ml-repo/app/ml_app");
    await screen.findByRole("navigation", { name: "Server" });
    const icons = Array.from(document.querySelectorAll(".nav-item svg")).map((s) => s.innerHTML);
    expect(icons).toHaveLength(7);
    expect(new Set(icons).size).toBe(7);
  });

  it("marks the active item and keeps disabled items as non-links with a reason", async () => {
    renderAt("/ws/team/app/ml_app");
    await waitFor(() => expect(wsSelect().value).toBe("team"));
    expect(screen.getByRole("link", { name: "Experiments" })).toHaveAttribute("aria-current", "page");
    const tree = screen.getByText("Stamp tree").closest(".nav-item")!;
    expect(tree.tagName).toBe("SPAN");
    expect(tree).toHaveAttribute("aria-disabled", "true");
    expect(tree).toHaveAttribute("title", "store workspace: no checkout");
    expect(screen.queryByRole("link", { name: "Stamp tree" })).toBeNull();
  });

  it("keeps the last workspace on /tokens", async () => {
    sessionStorage.setItem(LAST_WS_KEY, "ml-repo");
    renderAt("/tokens");
    await waitFor(() => expect(wsSelect().value).toBe("ml-repo"));
    expect(screen.getByRole("link", { name: "Models" })).toHaveAttribute("href", "/ws/ml-repo/models");
    expect(screen.getByRole("link", { name: "API tokens" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("button", { name: /choose app/ })).toBeInTheDocument();
  });

  it("shows workspace… for an unknown workspace, never the bogus name", async () => {
    renderAt("/ws/bogus");
    await screen.findByText("ml-repo — git");
    expect(wsSelect().value).toBe("");
    expect(screen.queryByText(/bogus/)).toBeNull();
  });

  it("shows the app's compact status rollup in the App group", async () => {
    renderAt("/ws/ml-repo/app/ml_app");
    const rollup = await screen.findByRole("link", { name: "2 stuck · 1 running" });
    expect(rollup).toHaveAttribute("href", "/ws/ml-repo/app/ml_app?status=stuck");
    expect(appStatus).toHaveBeenCalledWith("ml-repo", "ml_app");
  });

  it("passes focusMain and calls onNavigate only in the drawer", async () => {
    const onNavigate = vi.fn();
    const router = renderAt("/ws/ml-repo/app/ml_app", { onNavigate });
    fireEvent.click(await screen.findByRole("link", { name: "Models" }));
    expect(router.state.location.pathname).toBe("/ws/ml-repo/models");
    expect(router.state.location.state).toEqual({ focusMain: true });
    expect(onNavigate).toHaveBeenCalled();
  });

  it("passes focusMain from the wordmark, the select and the app menu in the drawer", async () => {
    const onNavigate = vi.fn();
    const router = renderAt("/ws/ml-repo/app/ml_app", { onNavigate });
    fireEvent.click(await screen.findByRole("button", { name: "ml_app" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "ml_app" }));
    expect(router.state.location.state).toEqual({ focusMain: true });
    await waitFor(() => expect(wsSelect().value).toBe("ml-repo"));
    fireEvent.change(wsSelect(), { target: { value: "team" } });
    expect(router.state.location.state).toEqual({ focusMain: true });
    fireEvent.click(screen.getByRole("link", { name: "vmn-exp" }));
    expect(router.state.location.state).toEqual({ home: true, focusMain: true });
    expect(onNavigate).toHaveBeenCalledTimes(3);
  });

  it("passes no state on desktop", async () => {
    const router = renderAt("/ws/ml-repo/app/ml_app");
    fireEvent.click(await screen.findByRole("link", { name: "Models" }));
    expect(router.state.location.state).toBeNull();
  });

  it("renders footExtra in the foot", () => {
    renderAt("/", { footExtra: <button>extra</button> });
    expect(screen.getByRole("button", { name: "extra" }).closest(".sidebar-foot")).not.toBeNull();
  });
});
