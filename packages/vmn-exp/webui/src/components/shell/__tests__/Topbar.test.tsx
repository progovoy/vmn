import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen } from "@testing-library/react";
import type { Meta } from "../../../types";
import { ctxOf, renderShell } from "./topbarFixtures";

const meta = vi.fn<() => Promise<Meta>>();
vi.mock("../../../api", () => ({ api: { meta: () => meta() } }));
vi.mock("../../../apiShell", () => ({ apiShell: { gitContext: vi.fn(() => new Promise(() => {})) } }));

import Topbar from "../Topbar";

type Props = Partial<Parameters<typeof Topbar>[0]>;
function renderTopbar(over: Parameters<typeof ctxOf>[0] = {}, props: Props = {}) {
  const handlers = { onSearch: vi.fn(), onSignOut: vi.fn() };
  const c = renderShell(
    <Topbar ctx={ctxOf(over)} crumbs={<nav aria-label="Breadcrumb">crumbs</nav>} {...handlers} {...props} />,
  ).container;
  return { c, ...handlers };
}

describe("Topbar", () => {
  beforeEach(() => { meta.mockResolvedValue({ version: "1" }); });

  it("renders the crumbs, search, theme and identity", () => {
    const { c, onSearch } = renderTopbar();
    expect(screen.getByRole("navigation", { name: "Breadcrumb" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^Search/ }));
    expect(onSearch).toHaveBeenCalledOnce();
    expect(screen.getByRole("button", { name: /^Theme:/ })).toBeInTheDocument();
    expect(c.querySelector(".id-chip")!.textContent).toContain("local");
  });

  it("shows the read-only badge titled with the reason", () => {
    const reason = "Your role in ml-repo is viewer";
    const { c } = renderTopbar({ readOnly: true, readOnlyReason: reason });
    const badge = c.querySelector(".ro-badge")!;
    expect(badge.textContent).toBe("read-only");
    expect(badge).toHaveAttribute("title", reason);
  });

  it("hides the badge when writes are allowed", () => {
    const { c } = renderTopbar();
    expect(c.querySelector(".ro-badge")).toBeNull();
  });

  it("offers the menu button only with onMenu, reflecting the drawer state", () => {
    renderTopbar();
    expect(screen.queryByRole("button", { name: "Open navigation" })).toBeNull();
  });

  it("menu button controls the sidebar and states whether it is open", () => {
    const onMenu = vi.fn();
    renderTopbar({}, { onMenu, menuOpen: true });
    const btn = screen.getByRole("button", { name: "Open navigation" });
    expect(btn).toHaveAttribute("aria-expanded", "true");
    expect(btn).toHaveAttribute("aria-controls", "sidebar");
    expect(btn.querySelector("svg")).not.toBeNull();
    fireEvent.click(btn);
    expect(onMenu).toHaveBeenCalledOnce();
  });

  it("passes sign out to the identity menu", () => {
    const { onSignOut } = renderTopbar({
      authEnabled: true,
      meta: {
        version: "1", principal: { id: "static-token", name: "static token" }, role: "admin",
        auth: { enabled: true, token: true, oidc: false, login_url: null },
      },
    });
    fireEvent.click(screen.getByRole("button", { name: /token · admin/ }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Sign out" }));
    expect(onSignOut).toHaveBeenCalledOnce();
  });

  it("colours the key cap --text-2 (Topbar.css)", async () => {
    // vitest stubs CSS imports (even ?raw) and the build has no node types: read the file.
    const fsModule = "node:fs";
    const { readFileSync } = await import(/* @vite-ignore */ fsModule);
    const topbarCss: string = readFileSync("src/components/shell/Topbar.css", "utf8");
    const rule = topbarCss.match(/\.search-key\s*\{([^}]*)\}/);
    expect(rule?.[1]).toMatch(/(^|[;\s])color:\s*var\(--text-2\)/);
  });
});
