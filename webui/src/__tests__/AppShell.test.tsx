import { describe, it, expect, vi, beforeEach, beforeAll, afterAll } from "vitest";
import { act, render, screen } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { useEffect } from "react";
import { createMemoryRouter, RouterProvider, useParams, type RouteObject } from "react-router-dom";

vi.mock("../api", () => ({
  api: {
    workspaces: vi.fn(), meta: vi.fn(), apps: vi.fn(),
    experimentsDiff: vi.fn(), metricsSchema: vi.fn(), recentExperiments: vi.fn(),
    experimentsPaged: vi.fn(),
  },
  appName: (t: string) => t.replaceAll("-", "/"),
  appTag: (n: string) => n.replaceAll("/", "-"),
}));

import { api } from "../api";
import App from "../App";
import { createQueryClient } from "../queryClient";
import { routes } from "../routes";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

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

let mounts = 0;
function Probe() {
  const { verstr } = useParams();
  useEffect(() => { mounts++; }, []);
  if (verstr === "bad") throw new Error("kaboom");
  return <div>probe {verstr}</div>;
}

function renderShell(tree: RouteObject[], path: string) {
  const router = createMemoryRouter(tree, { initialEntries: [path] });
  render(
    <QueryClientProvider client={createQueryClient()}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

const shellTree: RouteObject[] = [{
  path: "/", element: <App />,
  children: [{ path: "ws/:ws/app/:app/run/:verstr", element: <Probe />, handle: { page: "run" } }],
}];

beforeEach(() => {
  vi.clearAllMocks();
  mounts = 0;
  m.workspaces.mockResolvedValue([{ name: "w", kind: "local", path: "/tmp/w" }]);
  m.meta.mockResolvedValue({ version: "1.2.3" });
  m.apps.mockResolvedValue([]);
});

describe("App shell", () => {
  it("keeps the page mounted when only its params change", async () => {
    const router = renderShell(shellTree, "/ws/w/app/a/run/v1");
    expect(await screen.findByText("probe v1")).toBeInTheDocument();
    await act(async () => { await router.navigate("/ws/w/app/a/run/v2"); });
    expect(screen.getByText("probe v2")).toBeInTheDocument();
    expect(mounts).toBe(1);
  });

  it("clears a page error on navigation", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const router = renderShell(shellTree, "/ws/w/app/a/run/bad");
    expect(await screen.findByText(/something went wrong/i)).toBeInTheDocument();
    await act(async () => { await router.navigate("/ws/w/app/a/run/good"); });
    expect(screen.getByText("probe good")).toBeInTheDocument();
  });

  it("shows the vmn version from the shared cache", async () => {
    renderShell(shellTree, "/ws/w/app/a/run/v1");
    expect(await screen.findByText("vmn 1.2.3")).toBeInTheDocument();
  });
});

describe("routes", () => {
  it("lazy-loads a page behind a small fallback", async () => {
    m.experimentsDiff.mockResolvedValue({ from_verstr: "a", to_verstr: "b", metrics_delta: {}, diff: "" });
    m.metricsSchema.mockResolvedValue({});
    m.recentExperiments.mockResolvedValue([]);
    renderShell(routes, "/ws/w/app/a/compare?v=a&to=b");
    expect(document.querySelector(".route-fallback")).not.toBeNull();
    expect(await screen.findByText("Code diff")).toBeInTheDocument();
  });
});
