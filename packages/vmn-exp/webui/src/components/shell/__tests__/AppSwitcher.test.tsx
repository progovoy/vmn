import { describe, it, expect, vi, beforeAll, afterAll, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { createQueryClient } from "../../../queryClient";
import type { AppRow } from "../../../types";

const apps = vi.fn<(ws: string) => Promise<AppRow[]>>();
vi.mock("../../../api", () => ({
  api: { apps: (ws: string) => apps(ws) },
  appTag: (name: string) => name.replaceAll("/", "-"),
}));

import AppSwitcher from "../AppSwitcher";

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

function renderSwitcher(props: { ws?: string; app?: string; onNavigate?: () => void }) {
  const router = createMemoryRouter(
    [{ path: "*", element: <AppSwitcher {...props} /> }],
    { initialEntries: ["/ws/ml-repo"] },
  );
  render(
    <QueryClientProvider client={createQueryClient()}><RouterProvider router={router} /></QueryClientProvider>,
  );
  return router;
}

describe("AppSwitcher", () => {
  beforeEach(() => {
    apps.mockResolvedValue([
      { name: "ml_app", experiments: 3, versions: 1 },
      { name: "root/svc", experiments: 0, versions: 2 },
    ]);
  });

  it("is a menu button naming the current app", () => {
    renderSwitcher({ ws: "ml-repo", app: "ml_app" });
    const button = screen.getByRole("button", { name: "ml_app" });
    expect(button).toHaveAttribute("aria-haspopup", "menu");
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(button.querySelector("svg")).not.toBeNull();
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("reads choose app with no app in context", () => {
    renderSwitcher({ ws: "ml-repo" });
    expect(screen.getByRole("button", { name: "choose app" })).toBeEnabled();
  });

  it("is disabled with a reason with no workspace", () => {
    renderSwitcher({});
    const button = screen.getByRole("button", { name: "choose app" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("title", "choose a workspace first");
  });

  it("opens a menu of the workspace's apps as menuitem links", async () => {
    renderSwitcher({ ws: "ml-repo", app: "ml_app" });
    const button = screen.getByRole("button", { name: "ml_app" });
    fireEvent.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");
    const menu = screen.getByRole("menu");
    expect(menu).toHaveAttribute("aria-label", "Apps in ml-repo");
    const svc = await screen.findByRole("menuitem", { name: "root/svc" });
    expect(svc).toHaveAttribute("href", "/ws/ml-repo/app/root-svc");
    expect(screen.getByRole("menuitem", { name: "ml_app" })).toHaveAttribute("aria-current", "page");
    expect(apps).toHaveBeenCalledWith("ml-repo");
  });

  it("closes on Escape and returns focus to the button", async () => {
    renderSwitcher({ ws: "ml-repo", app: "ml_app" });
    const button = screen.getByRole("button", { name: "ml_app" });
    fireEvent.click(button);
    const first = await screen.findByRole("menuitem", { name: "ml_app" });
    first.focus();
    fireEvent.keyDown(first, { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
    expect(button).toHaveFocus();
    expect(button).toHaveAttribute("aria-expanded", "false");
  });

  it("moves focus between items with the arrow keys", async () => {
    renderSwitcher({ ws: "ml-repo", app: "ml_app" });
    fireEvent.click(screen.getByRole("button", { name: "ml_app" }));
    const first = await screen.findByRole("menuitem", { name: "ml_app" });
    const second = screen.getByRole("menuitem", { name: "root/svc" });
    first.focus();
    fireEvent.keyDown(first, { key: "ArrowDown" });
    expect(second).toHaveFocus();
    fireEvent.keyDown(second, { key: "ArrowDown" });
    expect(first).toHaveFocus();
    fireEvent.keyDown(first, { key: "ArrowUp" });
    expect(second).toHaveFocus();
  });

  it("navigates, closes and calls onNavigate on a pick", async () => {
    const onNavigate = vi.fn();
    const router = renderSwitcher({ ws: "ml-repo", app: "ml_app", onNavigate });
    fireEvent.click(screen.getByRole("button", { name: "ml_app" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "root/svc" }));
    expect(router.state.location.pathname).toBe("/ws/ml-repo/app/root-svc");
    expect(screen.queryByRole("menu")).toBeNull();
    expect(onNavigate).toHaveBeenCalled();
  });

  it("passes no state from a pick on desktop", async () => {
    const router = renderSwitcher({ ws: "ml-repo", app: "ml_app" });
    fireEvent.click(screen.getByRole("button", { name: "ml_app" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "root/svc" }));
    expect(router.state.location.state).toBeNull();
  });

  it("closes when Tab leaves the menu", async () => {
    renderSwitcher({ ws: "ml-repo", app: "ml_app" });
    fireEvent.click(screen.getByRole("button", { name: "ml_app" }));
    const first = await screen.findByRole("menuitem", { name: "ml_app" });
    fireEvent.keyDown(first, { key: "Tab" });
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("closes when the page scrolls or resizes under the fixed menu, not when the menu scrolls", async () => {
    renderSwitcher({ ws: "ml-repo", app: "ml_app" });
    const button = screen.getByRole("button", { name: "ml_app" });
    fireEvent.click(button);
    fireEvent.scroll(await screen.findByRole("menu"));
    expect(screen.getByRole("menu")).toBeInTheDocument();
    fireEvent.scroll(document);
    expect(screen.queryByRole("menu")).toBeNull();
    fireEvent.click(button);
    fireEvent(window, new Event("resize"));
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("says so when the workspace has no apps", async () => {
    apps.mockResolvedValue([]);
    renderSwitcher({ ws: "ml-repo" });
    fireEvent.click(screen.getByRole("button", { name: "choose app" }));
    expect(await screen.findByText("No apps in ml-repo yet")).toBeInTheDocument();
  });
});
