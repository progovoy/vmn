import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, within, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { ReactNode } from "react";
import type { CliCommand, Crumb } from "../../../shell/contracts";

const copyText = vi.fn<(text: string) => Promise<boolean>>();
vi.mock("../../../util", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../../util")>()),
  copyText: (text: string) => copyText(text),
}));

import Crumbs from "../Crumbs";

const BASE = "/ws/ml-repo/app/ml_app";
const RUN_CRUMBS: Crumb[] = [
  { label: "ml_app", to: BASE, mono: true },
  { label: "experiments", to: BASE },
  {
    label: "@54 lr-sweep-3", mono: true, title: "0.4.1-dev.abc",
    run: { verstr: "0.4.1-dev.abc", idx: 54, name: "lr-sweep-3" },
  },
];
const CLI: CliCommand[] = [
  { label: "show", command: "vmn-exp show ml_app -v 0.4.1-dev.abc" },
  { label: "restore", command: "vmn-exp restore ml_app -v 0.4.1-dev.abc" },
  { label: "goto", command: "vmn goto -v 0.4.1-dev.abc ml_app" },
];

function renderCrumbs(crumbs: Crumb[] = RUN_CRUMBS, cli: CliCommand[] = CLI, root?: ReactNode) {
  return render(<MemoryRouter><Crumbs root={root} crumbs={crumbs} cli={cli} /></MemoryRouter>);
}

describe("Crumbs", () => {
  beforeEach(() => {
    copyText.mockReset();
    copyText.mockResolvedValue(true);
  });

  it("is a breadcrumb list whose root comes first", () => {
    renderCrumbs(RUN_CRUMBS, CLI, <a href="/ws/ml-repo">ml-repo</a>);
    const nav = screen.getByRole("navigation", { name: "Breadcrumb" });
    const items = within(nav).getAllByRole("listitem");
    expect(items).toHaveLength(4);
    expect(items[0]).toHaveTextContent("ml-repo");
  });

  it("the leaf is the current page, never a link", () => {
    renderCrumbs();
    const nav = screen.getByRole("navigation", { name: "Breadcrumb" });
    const leaf = nav.querySelector('[aria-current="page"]')!;
    expect(leaf.tagName).toBe("SPAN");
    expect(leaf).toHaveTextContent("@54 lr-sweep-3");
    expect(leaf.closest("a")).toBeNull();
    expect(leaf).toHaveAttribute("title", "0.4.1-dev.abc");
    expect(within(nav).queryByRole("link", { name: /@54/ })).toBeNull();
  });

  it("parents link to their pages", () => {
    renderCrumbs();
    const list = screen.getByRole("list");
    expect(within(list).getByRole("link", { name: "ml_app" })).toHaveAttribute("href", BASE);
    expect(within(list).getByRole("link", { name: "experiments" })).toHaveAttribute("href", BASE);
  });

  it("the run leaf sets @N in mono apart from the name", () => {
    renderCrumbs();
    const leaf = document.querySelector('[aria-current="page"]')!;
    expect(leaf.querySelector(".mono")).toHaveTextContent("@54");
    expect(leaf.querySelector(".crumb-run-name")).toHaveTextContent("lr-sweep-3");
  });

  it("separators are hidden SVGs with no text", () => {
    renderCrumbs();
    const seps = document.querySelectorAll(".crumb-sep");
    expect(seps).toHaveLength(2);
    seps.forEach((s) => {
      expect(s.textContent).toBe("");
      expect(s.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
    });
    expect(screen.getByRole("navigation", { name: "Breadcrumb" }).textContent).not.toMatch(/[›>/]/);
  });

  it("copies the default command and announces it politely", async () => {
    renderCrumbs();
    fireEvent.click(screen.getByRole("button", { name: `Copy as CLI: ${CLI[0].command}` }));
    expect(copyText).toHaveBeenCalledWith(CLI[0].command);
    const live = screen.getByRole("status");
    expect(live).toHaveAttribute("aria-live", "polite");
    await waitFor(() => expect(live).toHaveTextContent("copied"));
  });

  it("the menu copies the other commands", async () => {
    renderCrumbs();
    const more = screen.getByRole("button", { name: "More CLI commands" });
    expect(more).toHaveAttribute("aria-haspopup", "menu");
    expect(more).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(more);
    const menu = screen.getByRole("menu");
    const items = within(menu).getAllByRole("menuitem");
    expect(items.map((i) => i.textContent)).toEqual([CLI[1].command, CLI[2].command]);
    fireEvent.click(items[1]);
    expect(copyText).toHaveBeenCalledWith(CLI[2].command);
    expect(screen.queryByRole("menu")).toBeNull();
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("copied"));
  });

  it("Escape closes the menu and returns focus", async () => {
    renderCrumbs();
    const more = screen.getByRole("button", { name: "More CLI commands" });
    fireEvent.click(more);
    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
    expect(more).toHaveFocus();
  });

  it("one command has no menu; none has no copy control", () => {
    const { unmount } = renderCrumbs(RUN_CRUMBS, CLI.slice(0, 1));
    expect(screen.getByRole("button", { name: /Copy as CLI/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "More CLI commands" })).toBeNull();
    unmount();
    renderCrumbs(RUN_CRUMBS, []);
    expect(screen.queryByRole("button", { name: /Copy as CLI/ })).toBeNull();
  });

  it("a back link leads to the parent crumb", () => {
    renderCrumbs();
    expect(screen.getByRole("link", { name: "Back to experiments" })).toHaveAttribute("href", BASE);
  });

  it("no back link for a lone leaf", () => {
    renderCrumbs([{ label: "workspaces" }], []);
    expect(screen.queryByRole("link", { name: /^Back to/ })).toBeNull();
  });
});
