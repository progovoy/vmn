/** One selection tray, mounted by the shell on every page of an app (the
 *  stamp tree, actions, compare-runs too). A board registers its actions
 *  with it; elsewhere it falls back to the generic ones. */
import { describe, it, expect, vi, beforeEach, beforeAll, afterAll } from "vitest";
import { act, render, screen, within } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider, type RouteObject } from "react-router-dom";

vi.mock("../api", () => ({
  api: {
    workspaces: vi.fn(), meta: vi.fn(), apps: vi.fn(),
    experimentsPaged: vi.fn(), recentExperiments: vi.fn(), facets: vi.fn(),
  },
  appName: (t: string) => t.replaceAll("-", "/"),
  appTag: (n: string) => n.replaceAll("/", "-"),
}));
vi.mock("../apiShell", () => ({
  apiShell: {
    gitContext: vi.fn(() => new Promise(() => {})),
    appStatus: vi.fn(() => new Promise(() => {})),
    resolveRef: vi.fn(() => Promise.resolve(null)),
  },
}));

import { api } from "../api";
import App from "../App";
import RouteError from "../components/shell/RouteError";
import { useTrayBoard } from "../pages/SelectionTrayHost";
import { createQueryClient } from "../queryClient";
import { writePicks } from "../util/runSelection";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

const NodeRequest = globalThis.Request;
beforeAll(() => {
  globalThis.Request = class extends NodeRequest {
    constructor(input: RequestInfo | URL, init?: RequestInit) {
      super(input, init && { ...init, signal: undefined });
    }
  } as typeof Request;
});
afterAll(() => { globalThis.Request = NodeRequest; });

const onSelectAll = vi.fn();
function BoardStub() {
  useTrayBoard({ total: 50, showUnarchive: false, onSelectAll });
  return <div>board page</div>;
}

const kid = (path: string, id: string, element: JSX.Element): RouteObject =>
  ({ path, element, handle: { id }, errorElement: <RouteError /> });
const tree: RouteObject[] = [{
  path: "/", element: <App />,
  children: [
    kid("ws/:ws", "apps", <div>apps page</div>),
    kid("ws/:ws/app/:app", "experiments", <BoardStub />),
    kid("ws/:ws/app/:app/tree", "tree", <div>tree page</div>),
    kid("ws/:ws/app/:app/actions", "actions", <div>actions page</div>),
    kid("ws/:ws/app/:app/compare-runs", "compare-runs", <div>compare page</div>),
  ],
}];

function renderAt(path: string) {
  const router = createMemoryRouter(tree, { initialEntries: [path] });
  render(
    <QueryClientProvider client={createQueryClient()}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}
const trays = () => screen.queryAllByRole("region", { name: "Selection" });

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  sessionStorage.clear();
  m.workspaces.mockResolvedValue([{ name: "w", kind: "git", path: "/tmp/w" }]);
  m.meta.mockResolvedValue({ version: "1.2.3" });
  m.apps.mockResolvedValue([]);
  m.experimentsPaged.mockResolvedValue({ rows: [], total: 0 });
  m.recentExperiments.mockResolvedValue([]);
  writePicks("w", "a", [{ verstr: "v1", job: "J1" }, { verstr: "v2", job: "J2" }]);
});

describe("the app-wide tray", () => {
  it.each([
    ["stamp tree", "/ws/w/app/a/tree", "tree page"],
    ["actions", "/ws/w/app/a/actions", "actions page"],
    ["compare-runs", "/ws/w/app/a/compare-runs", "compare page"],
  ])("shows on the %s page", async (_name, path, text) => {
    renderAt(path);
    await screen.findByText(text);
    expect(trays()).toHaveLength(1);
    expect(within(trays()[0]).getByRole("status")).toHaveTextContent("2 selected from 2 jobs");
  });

  it("is not shown outside an app", async () => {
    renderAt("/ws/w");
    await screen.findByText("apps page");
    expect(trays()).toHaveLength(0);
  });

  it("takes a board's actions while the board is on screen, then falls back", async () => {
    const router = renderAt("/ws/w/app/a");
    await screen.findByText("board page");
    expect(trays()).toHaveLength(1);
    expect(within(trays()[0]).getByRole("button", { name: "Select all 50 matching" })).toBeInTheDocument();
    await act(async () => { await router.navigate("/ws/w/app/a/tree"); });
    await screen.findByText("tree page");
    expect(trays()).toHaveLength(1);
    expect(within(trays()[0]).queryByRole("button", { name: /select all/i })).toBeNull();
  });
});
