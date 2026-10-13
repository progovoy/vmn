/** The assembled shell (plan 19 §1.1, U9): landmarks, skip link, the router's
 *  not-found and error pages inside the frame, titles, ⌘K and sign-in. */
import { describe, it, expect, vi, beforeEach, beforeAll, afterAll, afterEach } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider, type RouteObject } from "react-router-dom";
import { useEffect, useState } from "react";

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
import { clearUnauthorized, reportUnauthorized } from "../auth/authState";
import RouteError from "../components/shell/RouteError";
import NotFound from "../components/shell/NotFound";
import { createQueryClient } from "../queryClient";
import { routes } from "../routes";
import { RECENT_KEY } from "../shell/contracts";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

// Node's Request rejects jsdom's AbortSignal (see AppShell.test.tsx).
const NodeRequest = globalThis.Request;
beforeAll(() => {
  globalThis.Request = class extends NodeRequest {
    constructor(input: RequestInfo | URL, init?: RequestInit) {
      super(input, init && { ...init, signal: undefined });
    }
  } as typeof Request;
});
afterAll(() => { globalThis.Request = NodeRequest; });

function Boom(): never { throw new Error("kaboom"); }

/** A page that learns only after loading that its subject is gone. */
function LateNotFound() {
  const [gone, setGone] = useState(false);
  useEffect(() => { setTimeout(() => setGone(true), 10); }, []);
  return gone ? <NotFound kind="route" pathname="/ws/w/gone" /> : <div>loading page</div>;
}

const frameTree: RouteObject[] = [{
  path: "/", element: <App />,
  children: [
    { index: true, element: <div>home page</div>, handle: { id: "home" }, errorElement: <RouteError /> },
    { path: "ws/:ws", element: <div>apps page</div>, handle: { id: "apps" }, errorElement: <RouteError /> },
    { path: "boom", element: <Boom />, handle: { id: "home" }, errorElement: <RouteError /> },
    { path: "ws/:ws/gone", element: <LateNotFound />, handle: { id: "apps" }, errorElement: <RouteError /> },
  ],
}];

function renderShell(tree: RouteObject[], path: string) {
  const router = createMemoryRouter(tree, { initialEntries: [path] });
  render(
    <QueryClientProvider client={createQueryClient()}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

const FOCUSABLE = "a[href], button:not([disabled]), input, select, textarea, [tabindex]:not([tabindex='-1'])";

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  m.workspaces.mockResolvedValue([{ name: "w", kind: "git", path: "/tmp/w" }]);
  m.meta.mockResolvedValue({ version: "1.2.3" });
  m.apps.mockResolvedValue([]);
  m.experimentsPaged.mockResolvedValue({ rows: [], total: 0 });
  m.recentExperiments.mockResolvedValue([]);
});
afterEach(() => { act(() => clearUnauthorized()); });

describe("shell frame", () => {
  it("makes the skip link the first tab stop, pointing at main#main", async () => {
    renderShell(frameTree, "/");
    await screen.findByText("home page");
    const first = document.querySelector<HTMLElement>(FOCUSABLE);
    expect(first).toHaveClass("skip-link");
    expect(first).toHaveAttribute("href", "#main");
    expect(first).toHaveTextContent("Skip to content");
    const main = screen.getByRole("main");
    expect(main).toHaveAttribute("id", "main");
    expect(main).toHaveAttribute("tabindex", "-1");
  });

  it("puts the sidebar in an aside#sidebar and the topbar in a banner", async () => {
    renderShell(frameTree, "/");
    await screen.findByText("home page");
    expect(screen.getByRole("complementary")).toHaveAttribute("id", "sidebar");
    expect(within(screen.getByRole("banner")).getByRole("navigation", { name: "Breadcrumb" })).toBeInTheDocument();
  });

  it("never shows the old pulsing host chip", async () => {
    renderShell(frameTree, "/ws/w");
    await screen.findByText("apps page");
    expect(document.querySelector(".pulse")).toBeNull();
    expect(document.querySelector(".host-chip")).toBeNull();
  });

  it("titles the page per route", async () => {
    const router = renderShell(frameTree, "/");
    await waitFor(() => expect(document.title).toBe("workspaces — vmn-exp"));
    await act(async () => { await router.navigate("/ws/w"); });
    await waitFor(() => expect(document.title).toBe("w — vmn-exp"));
  });

  it("remembers visited pages for ⌘K's Recent section", async () => {
    renderShell(frameTree, "/ws/w");
    await screen.findByText("apps page");
    await waitFor(() => {
      const recents = JSON.parse(localStorage.getItem(RECENT_KEY) ?? "[]");
      expect(recents[0]).toMatchObject({ to: "/ws/w", label: "w" });
    });
  });

  it("forgets a destination for ⌘K's Recent once it turns out missing", async () => {
    const router = renderShell(frameTree, "/ws/w");
    await screen.findByText("apps page");
    await act(async () => { await router.navigate("/ws/w/gone"); });
    await screen.findByText("loading page");
    await screen.findByRole("heading", { name: /No page/ });
    await waitFor(() => {
      const recents: { to: string }[] = JSON.parse(localStorage.getItem(RECENT_KEY) ?? "[]");
      expect(recents.map((r) => r.to)).toEqual(["/ws/w"]);
    });
  });

  it("never keeps a page that failed to render in ⌘K's Recent", async () => {
    const router = renderShell(frameTree, "/ws/w");
    await screen.findByText("apps page");
    await act(async () => { await router.navigate("/boom"); });
    await screen.findByRole("heading", { name: "This page failed to render" });
    await new Promise((r) => setTimeout(r, 20));
    const recents: { to: string }[] = JSON.parse(localStorage.getItem(RECENT_KEY) ?? "[]");
    expect(recents.map((r) => r.to)).toEqual(["/ws/w"]);
  });

  it("moves focus to main and announces the title after a palette or drawer navigation", async () => {
    const router = renderShell(frameTree, "/");
    await screen.findByText("home page");
    await act(async () => { await router.navigate("/ws/w", { state: { focusMain: true } }); });
    await waitFor(() => expect(screen.getByRole("main")).toHaveFocus());
    await waitFor(() => expect(document.querySelector(".shell-announce")).toHaveTextContent("w — vmn-exp"));
  });

  it("does not move focus on a plain navigation", async () => {
    const router = renderShell(frameTree, "/");
    await screen.findByText("home page");
    await act(async () => { await router.navigate("/ws/w"); });
    await screen.findByText("apps page");
    expect(screen.getByRole("main")).not.toHaveFocus();
  });
});

describe("router pages inside the shell", () => {
  it("keeps the sidebar on a bogus URL and shows the route not-found", async () => {
    renderShell(routes, "/no/such/page");
    expect(await screen.findByRole("heading", { name: "No page at this address" })).toBeInTheDocument();
    expect(screen.getByRole("complementary")).toBeInTheDocument();
    await waitFor(() => expect(document.title).toBe("not found — vmn-exp"));
  });

  it("leaves the root empty when no workspace is in context, so CSS drops it and its separator", async () => {
    sessionStorage.clear();
    renderShell(routes, "/no/such/page");
    await waitFor(() => expect(document.title).toBe("not found — vmn-exp"));
    const nav = screen.getByRole("navigation", { name: "Breadcrumb" });
    const leaf = within(nav).getByText("not found").closest("li")!;
    // Crumbs.css hides `.crumb-root:empty` and the separator right after it.
    expect(leaf.previousElementSibling?.matches(".crumb-root:empty")).toBe(true);
    expect(leaf.matches(".crumb-root:empty + .crumb")).toBe(true);
    expect(within(nav).queryAllByRole("listitem").filter((li) => li.textContent)).toHaveLength(1);
  });

  it("shows RouteError inside the shell when a page throws", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    renderShell(frameTree, "/boom");
    const main = await screen.findByRole("main");
    expect(await within(main).findByRole("heading", { name: "This page failed to render" })).toBeInTheDocument();
    expect(screen.getByRole("complementary")).toBeInTheDocument();
  });

  it("gives every child route an id handle and the RouteError element", () => {
    for (const child of routes[0].children ?? []) {
      expect(child.handle, child.path ?? "index").toHaveProperty("id");
      expect(child.errorElement, child.path ?? "index").toBeTruthy();
    }
    expect(routes[0].errorElement).toBeUndefined();
    expect(routes[0].children?.some((r) => r.path === "*")).toBe(true);
  });
});

describe("command palette", () => {
  it("toggles with Ctrl+K and makes the shell inert while open", async () => {
    renderShell(frameTree, "/");
    await screen.findByText("home page");
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    expect(await screen.findByRole("dialog", { name: "Command palette" })).toBeInTheDocument();
    expect(document.querySelector(".shell")).toHaveAttribute("inert");
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(document.querySelector(".shell")).not.toHaveAttribute("inert");
  });

  it("moves focus to main after a palette navigation", async () => {
    renderShell(frameTree, "/");
    await screen.findByText("home page");
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const dialog = await screen.findByRole("dialog", { name: "Command palette" });
    const input = within(dialog).getByRole("combobox");
    fireEvent.change(input, { target: { value: "ws w" } });
    await screen.findByRole("option", { name: /ws w/ });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(await screen.findByText("apps page")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("main")).toHaveFocus());
  });

  it("opens from the topbar's search button", async () => {
    renderShell(frameTree, "/");
    await screen.findByText("home page");
    fireEvent.click(within(screen.getByRole("banner")).getByRole("button", { name: /search/i }));
    expect(await screen.findByRole("dialog", { name: "Command palette" })).toBeInTheDocument();
  });
});

describe("below 900px", () => {
  const originalMatchMedia = window.matchMedia;
  beforeEach(() => {
    window.matchMedia = ((query: string) => ({
      matches: query === "(max-width: 899px)", media: query,
      addEventListener: () => {}, removeEventListener: () => {},
    })) as unknown as typeof window.matchMedia;
  });
  afterEach(() => { window.matchMedia = originalMatchMedia; });

  it("opens the sidebar as a drawer from the topbar's menu button", async () => {
    renderShell(frameTree, "/ws/w");
    await screen.findByText("apps page");
    const sidebar = screen.getByRole("complementary", { hidden: true });
    expect(sidebar).toHaveAttribute("inert");
    const menu = screen.getByRole("button", { name: "Open navigation" });
    expect(menu).toHaveAttribute("aria-controls", "sidebar");
    fireEvent.click(menu);
    expect(menu).toHaveAttribute("aria-expanded", "true");
    expect(sidebar).not.toHaveAttribute("inert");
    expect(document.querySelector(".main-col")).toHaveAttribute("inert");
    expect(document.querySelector(".drawer-veil")).not.toBeNull();
    fireEvent.click(document.querySelector(".drawer-veil")!);
    expect(document.querySelector(".drawer-veil")).toBeNull();
  });
});

describe("sign-in", () => {
  it("swaps the page for the sign-in page on a GET 401, keeping the sidebar", async () => {
    renderShell(frameTree, "/ws/w");
    await screen.findByText("apps page");
    act(() => reportUnauthorized({ hints: { token: true, oidc: false, login_url: null }, method: "GET" }));
    const main = screen.getByRole("main");
    expect(await within(main).findByRole("heading", { name: "Sign in to vmn-exp ui" })).toBeInTheDocument();
    expect(screen.queryByText("apps page")).toBeNull();
    expect(screen.getByRole("complementary")).toBeInTheDocument();
    await waitFor(() => expect(document.title).toBe("sign in — vmn-exp"));
  });
});

describe("app status", () => {
  beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }));
  afterEach(() => vi.useRealTimers());

  it("is polled once by the shell on an app page, whoever else reads it", async () => {
    const appStatus = (await import("../apiShell")).apiShell.appStatus as ReturnType<typeof vi.fn>;
    appStatus.mockResolvedValue({
      total: 1, counts: { created: 0, running: 1, stuck: 0, succeeded: 0, failed: 0 },
      failed_recent: 0, rollup: "running",
    });
    const tree: RouteObject[] = [{
      path: "/", element: <App />,
      children: [{ path: "ws/:ws/app/:app", element: <div>board</div>, handle: { id: "experiments" } }],
    }];
    renderShell(tree, "/ws/w/app/ml_app");
    await screen.findByText("board");
    await waitFor(() => expect(appStatus).toHaveBeenCalledTimes(1));
    await act(async () => { await vi.advanceTimersByTimeAsync(15_500); });
    expect(appStatus).toHaveBeenCalledTimes(2);
  });
});
