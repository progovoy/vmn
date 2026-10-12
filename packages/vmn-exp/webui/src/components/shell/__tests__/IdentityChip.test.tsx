import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import type { Meta } from "../../../types";
import { ctxOf, ML_REPO, renderShell, TEAM } from "./topbarFixtures";

const meta = vi.fn<() => Promise<Meta>>();
vi.mock("../../../api", () => ({ api: { meta: () => meta() } }));

import IdentityChip, { isLoopback } from "../IdentityChip";

const AUTH = { enabled: true, token: true, oidc: true, login_url: "/auth/login" };
const chip = (c: HTMLElement) => c.querySelector(".id-chip");

function renderChip(over: Parameters<typeof ctxOf>[0], onSignOut = vi.fn()) {
  const c = renderShell(<IdentityChip ctx={ctxOf(over)} onSignOut={onSignOut} />).container;
  return { c, onSignOut };
}

describe("IdentityChip", () => {
  beforeEach(() => {
    meta.mockReset();
    meta.mockResolvedValue({ version: "0.10.2" });
  });

  it("says local, with no menu, when auth is off on a loopback host", () => {
    const { c } = renderChip({ meta: { version: "1" } });
    expect(chip(c)!.textContent).toContain("local");
    expect(chip(c)).toHaveAttribute("title", `vmn-exp ui on ${location.host}: no sign-in`);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("names the host when auth is off elsewhere (only loopback reads local)", () => {
    expect(["localhost", "127.0.0.1", "127.1.2.3", "::1", "[::1]"].every(isLoopback)).toBe(true);
    expect(["exp.example.com", "10.0.0.1", "localhost.evil.com"].some(isLoopback)).toBe(false);
  });

  it("shows token · admin for the static token, with a sign-out menu", () => {
    const { onSignOut } = renderChip({
      authEnabled: true, role: "admin",
      meta: { version: "1", auth: AUTH, principal: { id: "static-token", name: "static token" }, role: "admin" },
    });
    const btn = screen.getByRole("button", { name: /token · admin/ });
    expect(btn).toHaveAttribute("aria-haspopup", "menu");
    expect(btn).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(btn);
    expect(btn).toHaveAttribute("aria-expanded", "true");
    const items = screen.getAllByRole("menuitem");
    expect(items.map((i) => i.textContent)).toEqual(["Sign out"]);
    fireEvent.click(items[0]);
    expect(onSignOut).toHaveBeenCalledOnce();
  });

  it("shows a signed-in user's name and workspace role, with roles, CLI login and sign out", async () => {
    const writeText = vi.fn(() => Promise.resolve());
    Object.assign(navigator, { clipboard: { writeText } });
    renderChip({
      ws: "ml-repo", workspace: { ...ML_REPO, role: "editor" },
      workspaces: [{ ...ML_REPO, role: "editor" }, { ...TEAM, role: null }],
      authEnabled: true, role: "editor",
      meta: { version: "1", auth: AUTH, principal: { id: "u1", name: "Ada" }, role: null },
    });
    fireEvent.click(screen.getByRole("button", { name: /Ada · editor/ }));
    const roles = screen.getByRole("list", { name: "Workspace roles" });
    expect(roles.textContent).toMatch(/ml-repo\s*editor/);
    expect(roles.textContent).toMatch(/team\s*no role/);
    const items = screen.getAllByRole("menuitem").map((i) => i.textContent);
    expect(items).toEqual(["Copy CLI login", "Sign out"]);
    fireEvent.click(screen.getByRole("menuitem", { name: "Copy CLI login" }));
    await waitFor(() => expect(writeText).toHaveBeenCalled());
    expect(writeText).toHaveBeenCalledWith(`vmn-exp login --server ${location.origin}`);
  });

  it("omits the role when the user has none", () => {
    renderChip({
      authEnabled: true, role: null,
      meta: { version: "1", auth: AUTH, principal: { id: "u1", name: "Ada" }, role: null },
    });
    const btn = screen.getByRole("button", { name: /Ada/ });
    expect(btn.textContent).not.toContain("·");
  });

  it("closes its menu on Escape and returns focus to the chip", () => {
    renderChip({
      authEnabled: true,
      meta: { version: "1", auth: AUTH, principal: { id: "static-token", name: "static token" }, role: "admin" },
    });
    const btn = screen.getByRole("button", { name: /token/ });
    fireEvent.click(btn);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
    expect(btn).toHaveFocus();
  });

  it("moves between menu items with the arrow keys, wrapping, and Home/End", () => {
    renderChip({
      ws: "ml-repo", workspace: ML_REPO, authEnabled: true, role: "editor",
      meta: { version: "1", auth: AUTH, principal: { id: "u1", name: "Ada" }, role: "editor" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Ada/ }));
    const [copy, signOut] = screen.getAllByRole("menuitem");
    expect(copy).toHaveFocus();
    const menu = screen.getByRole("menu");
    fireEvent.keyDown(menu, { key: "ArrowDown" });
    expect(signOut).toHaveFocus();
    fireEvent.keyDown(menu, { key: "ArrowDown" });
    expect(copy).toHaveFocus();
    fireEvent.keyDown(menu, { key: "ArrowUp" });
    expect(signOut).toHaveFocus();
    fireEvent.keyDown(menu, { key: "Home" });
    expect(copy).toHaveFocus();
    fireEvent.keyDown(menu, { key: "End" });
    expect(signOut).toHaveFocus();
  });

  it("closes its menu when Tab moves focus out of it", () => {
    renderChip({
      authEnabled: true,
      meta: { version: "1", auth: AUTH, principal: { id: "static-token", name: "static token" }, role: "admin" },
    });
    fireEvent.click(screen.getByRole("button", { name: /token/ }));
    fireEvent.keyDown(screen.getByRole("menu"), { key: "Tab" });
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("says not signed in on a 401, with no menu", () => {
    const { c } = renderChip({ metaStatus: "unauthorized", meta: undefined, authEnabled: false });
    expect(chip(c)!.textContent).toContain("not signed in");
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("says no access on a 403, titled with the server's detail, with sign out", async () => {
    meta.mockRejectedValue(Object.assign(new Error("Forbidden: no role"), { status: 403 }));
    const { onSignOut } = renderChip({ metaStatus: "forbidden", meta: undefined });
    const btn = screen.getByRole("button", { name: /no access/ });
    await waitFor(() => expect(btn).toHaveAttribute("title", "Forbidden: no role"));
    fireEvent.click(btn);
    fireEvent.click(screen.getByRole("menuitem", { name: "Sign out" }));
    expect(onSignOut).toHaveBeenCalledOnce();
  });

  it("says server unreachable in the bad colour with an icon, titled retrying…", () => {
    const { c } = renderChip({ metaStatus: "unreachable", metaError: true, meta: undefined });
    expect(chip(c)!.textContent).toContain("server unreachable");
    expect(chip(c)).toHaveClass("bad");
    expect(chip(c)).toHaveAttribute("title", "retrying…");
    expect(chip(c)!.querySelector("svg")).not.toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("renders nothing while loading", () => {
    const { c } = renderChip({ metaStatus: "loading", meta: undefined });
    expect(c.textContent).toBe("");
  });

  it("never pulses", () => {
    for (const over of [
      {}, { metaStatus: "unreachable" as const, metaError: true, meta: undefined },
      { authEnabled: true, meta: { version: "1", auth: AUTH, principal: { id: "u", name: "Ada" } } },
    ]) {
      const { c } = renderChip(over);
      expect(c.querySelector(".pulse")).toBeNull();
    }
  });
});
